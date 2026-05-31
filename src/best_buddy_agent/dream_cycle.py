"""Dream cycle: nightly memory maintenance adapted from Thoth.

Five phases:
    1. Duplicate merge  — name guard, alias promotion, batch rotation
    2. Enrichment       — thin descriptions filled from conversation evidence
    3. Confidence decay — inferred edges lose score over time; pruned at 0.30
    4. Relation inference — co-occurrence analysis with rejection cache
    5. Insights          — LLM health snapshot of the overall system
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from . import knowledge_graph as kg
from .config import load_config
from .llm_runner import run_text_completion
from .threads import list_threads, thread_conversation_rows

logger = logging.getLogger(__name__)

_DATA_DIR = pathlib.Path(
    os.environ.get("BEST_BUDDY_AGENT_DATA_DIR", pathlib.Path.home() / ".best_buddy_agent")
)
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_CONFIG_FILE = _DATA_DIR / "dream_config.json"
_JOURNAL_FILE = _DATA_DIR / "dream_journal.json"
_REJECTION_CACHE_FILE = _DATA_DIR / "dream_rejections.json"

_DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "window_start": 1,
    "window_end": 5,
    "merge_threshold": 0.93,
    "infer_confidence": 0.80,
    "min_entities": 20,
    "batch_size": 50,
    "batch_offset": 0,
}

_REJECTION_TTL_DAYS = 7
_HUB_CAP = 3
_ENRICH_MIN_CHARS = 80
_ENRICH_MIN_CONVS = 2
_ENRICH_KEYWORD_RATIO = 0.40
_DECAY_DAYS = 90
_PRUNE_THRESHOLD = 0.30
_DECAY_FACTOR = 0.90


# ─────────────────────────────────────────────────────────────────
# Config helpers
# ─────────────────────────────────────────────────────────────────

def _load_dream_config() -> dict:
    if _CONFIG_FILE.exists():
        try:
            cfg = json.loads(_CONFIG_FILE.read_text())
            return {**_DEFAULT_CONFIG, **cfg}
        except Exception:
            pass
    return dict(_DEFAULT_CONFIG)


def _save_dream_config(cfg: dict) -> None:
    _CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def _append_journal(entry: dict) -> None:
    journal: list[dict] = []
    if _JOURNAL_FILE.exists():
        try:
            journal = json.loads(_JOURNAL_FILE.read_text())
        except Exception:
            journal = []
    journal.append(entry)
    _JOURNAL_FILE.write_text(json.dumps(journal[-100:], indent=2))


# ─────────────────────────────────────────────────────────────────
# Rejection cache
# ─────────────────────────────────────────────────────────────────

def _load_rejection_cache() -> dict[str, str]:
    """Load {pair_key: iso_timestamp} rejection cache."""
    if _REJECTION_CACHE_FILE.exists():
        try:
            return json.loads(_REJECTION_CACHE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_rejection_cache(cache: dict[str, str]) -> None:
    _REJECTION_CACHE_FILE.write_text(json.dumps(cache, indent=2))


def _pair_key(id_a: str, id_b: str) -> str:
    return "__".join(sorted([id_a, id_b]))


def _record_rejection(ea_id: str, eb_id: str) -> None:
    cache = _load_rejection_cache()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_REJECTION_TTL_DAYS)).isoformat()
    # Clean up expired entries
    cache = {k: v for k, v in cache.items() if v >= cutoff}
    cache[_pair_key(ea_id, eb_id)] = datetime.now(timezone.utc).isoformat()
    _save_rejection_cache(cache)


def _is_pair_recently_rejected(ea_id: str, eb_id: str) -> bool:
    cache = _load_rejection_cache()
    ts = cache.get(_pair_key(ea_id, eb_id))
    if not ts:
        return False
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_REJECTION_TTL_DAYS)).isoformat()
    return ts >= cutoff


# ─────────────────────────────────────────────────────────────────
# Dream guard predicates
# ─────────────────────────────────────────────────────────────────

def _already_ran_today() -> bool:
    if not _JOURNAL_FILE.exists():
        return False
    try:
        journal = json.loads(_JOURNAL_FILE.read_text())
        if not journal:
            return False
        last_ts = journal[-1].get("timestamp", "")
        return last_ts[:10] == datetime.now().strftime("%Y-%m-%d")
    except Exception:
        return False


def _is_idle() -> bool:
    from .memory_extraction import _active_threads  # noqa: PLC0415
    return len(_active_threads) == 0


def _is_ollama_busy() -> bool:
    try:
        import urllib.request  # noqa: PLC0415
        cfg = load_config()
        url = f"http://{cfg.llm_host}:{cfg.llm_port}/api/ps"
        with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310
            data = json.loads(resp.read())
            return int(data.get("num_requests", 0)) > 0
    except Exception:
        return False


def _should_dream(cfg: dict) -> bool:
    if not cfg.get("enabled", True):
        return False
    now = datetime.now()
    w_start = cfg.get("window_start", 1)
    w_end = cfg.get("window_end", 5)
    if not (w_start <= now.hour < w_end):
        return False
    if _already_ran_today():
        return False
    if not _is_idle():
        return False
    if _is_ollama_busy():
        return False
    return True


# ─────────────────────────────────────────────────────────────────
# Phase 1 — Duplicate merge
# ─────────────────────────────────────────────────────────────────

def _llm_merge_description(entity_a: dict, entity_b: dict) -> str:
    cfg = load_config()
    prompt = cfg.prompts.format(
        "dream/merge",
        entity_type=entity_a.get("entity_type", "fact"),
        subject_a=entity_a.get("subject", ""),
        description_a=entity_a.get("description", entity_a.get("content", "")),
        subject_b=entity_b.get("subject", ""),
        description_b=entity_b.get("description", entity_b.get("content", "")),
    )
    text = run_text_completion(cfg, prompt).strip()
    if len(text) < 10:
        desc_a = entity_a.get("description", entity_a.get("content", ""))
        desc_b = entity_b.get("description", entity_b.get("content", ""))
        return f"{desc_a}. {desc_b}".strip(". ")
    return text


def _union_aliases(survivor: dict, duplicate: dict) -> str:
    """Return merged alias string: survivor aliases ∪ duplicate aliases ∪ duplicate subject."""
    def _split(s: str) -> set[str]:
        return {a.strip() for a in s.split(",") if a.strip()}

    aliases = _split(survivor.get("aliases") or "")
    aliases |= _split(duplicate.get("aliases") or "")
    dup_subject = (duplicate.get("subject") or "").strip()
    if dup_subject and dup_subject != survivor.get("subject", ""):
        aliases.add(dup_subject)
    aliases.discard(survivor.get("subject", ""))
    return ", ".join(sorted(aliases))


def _merge_one_pair(a: dict, b: dict) -> dict | None:
    # Keep the older entity as survivor (more likely to have more connections)
    survivor, duplicate = (
        (a, b) if a.get("created_at", "") <= b.get("created_at", "") else (b, a)
    )
    # Never merge User entity
    if (survivor.get("subject") or "").strip().lower() == "user":
        return None
    if (duplicate.get("subject") or "").strip().lower() == "user":
        return None

    merged_desc = _llm_merge_description(survivor, duplicate)
    merged_aliases = _union_aliases(survivor, duplicate)

    kg.update_entity(survivor["id"], merged_desc, aliases=merged_aliases)

    # Re-point all edges from duplicate to survivor (skip self-loops)
    for rel in kg.get_relations(duplicate["id"], direction="both"):
        src = survivor["id"] if rel["source_id"] == duplicate["id"] else rel["source_id"]
        tgt = survivor["id"] if rel["target_id"] == duplicate["id"] else rel["target_id"]
        if src == tgt:
            continue
        kg.add_relation(
            src, tgt, rel["relation_type"],
            confidence=rel.get("confidence", 0.8),
            source="dream_merge",
        )

    kg.delete_entity(duplicate["id"])
    return {
        "survivor_id": survivor["id"],
        "duplicate_id": duplicate["id"],
        "survivor_subject": survivor.get("subject", ""),
        "duplicate_subject": duplicate.get("subject", ""),
        "aliases_added": merged_aliases,
    }


def _run_merge_phase(all_entities: list[dict], cfg: dict) -> list[dict]:
    """Phase 1: find near-duplicate entity pairs and merge them."""
    merges: list[dict] = []
    threshold = cfg.get("merge_threshold", 0.93)
    batch_size = cfg.get("batch_size", 50)
    batch_offset = cfg.get("batch_offset", 0)

    # Batch rotation: advance by half batch each cycle
    start = batch_offset % max(len(all_entities), 1)
    batch = (all_entities + all_entities)[start: start + batch_size]
    new_offset = (batch_offset + batch_size // 2) % max(len(all_entities), 1)
    cfg["batch_offset"] = new_offset
    _save_dream_config(cfg)

    processed: set[str] = set()

    for ent in batch:
        eid = ent["id"]
        if eid in processed:
            continue

        desc = ent.get("description", ent.get("content", ""))
        query = f"{ent.get('entity_type', '')} {ent.get('subject', '')} {desc}"
        try:
            hits = kg.semantic_search(query, top_k=3, threshold=threshold)
        except Exception:
            continue

        for h in hits:
            if h["id"] == eid or h["id"] in processed:
                continue
            if h.get("entity_type") != ent.get("entity_type"):
                continue

            subj_a = (ent.get("subject") or "").strip()
            subj_b = (h.get("subject") or "").strip()

            # Name guard: if subjects are completely different (neither substring
            # of the other), require a tighter similarity score of 0.98
            score = h.get("score", 0.0)
            names_match = (
                subj_a.lower() == subj_b.lower()
                or subj_a.lower() in subj_b.lower()
                or subj_b.lower() in subj_a.lower()
            )
            if not names_match and score < 0.98:
                continue

            result = _merge_one_pair(ent, h)
            if result:
                merges.append(result)
                processed.add(eid)
                processed.add(h["id"])
            break

    return merges


# ─────────────────────────────────────────────────────────────────
# Phase 2 — Description enrichment
# ─────────────────────────────────────────────────────────────────

def _extract_relevant_sentences(text: str, names: set[str]) -> str:
    """Return sentences from text that mention any name in names."""
    sentence_pat = re.compile(r"(?<=[.!?\n])\s+")
    # Split on sentence boundaries AND turn markers
    parts = re.split(r"(?<=[.!?])\s+|(?=User:|Assistant:|System:)", text)
    relevant = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        for name in names:
            if re.search(r"\b" + re.escape(name) + r"\b", part, re.IGNORECASE):
                relevant.append(part)
                break
    return " ".join(relevant[:10])  # cap at 10 sentences


def _find_conversation_mentions(subject: str, aliases: str = "") -> list[str]:
    """Scan all threads for sentences mentioning this entity."""
    names: set[str] = {subject}
    if aliases:
        names |= {a.strip() for a in aliases.split(",") if a.strip()}

    excerpts: list[str] = []
    try:
        threads = list_threads()
        for t in threads[:30]:  # cap threads to avoid huge scan
            rows = thread_conversation_rows(t.get("id", ""))
            full_text = " ".join(
                (r.get("content") or "") for r in rows if r.get("role") == "user"
            )
            excerpt = _extract_relevant_sentences(full_text, names)
            if excerpt:
                excerpts.append(excerpt)
            if len(excerpts) >= _ENRICH_MIN_CONVS + 2:
                break
    except Exception:
        pass
    return excerpts


def _ground_check(new_desc: str, old_desc: str, excerpts: list[str]) -> bool:
    """Check that at least 40% of key words in new_desc appear in source material."""
    source_text = " ".join(excerpts) + " " + old_desc
    words = re.findall(r"\b\w{4,}\b", new_desc.lower())
    if not words:
        return False
    grounded = sum(1 for w in words if w in source_text.lower())
    return (grounded / len(words)) >= _ENRICH_KEYWORD_RATIO


def _run_enrichment_phase(all_entities: list[dict]) -> list[dict]:
    """Phase 2: enrich entities with thin descriptions."""
    enriched: list[dict] = []
    # Find subjects for contamination check
    all_subjects = {(e.get("subject") or "").strip() for e in all_entities}

    thin = [
        e for e in all_entities
        if len((e.get("description") or e.get("content") or "")) < _ENRICH_MIN_CHARS
        and (e.get("subject") or "").strip().lower() != "user"
    ]

    for ent in thin[:20]:
        subject = (ent.get("subject") or "").strip()
        aliases = (ent.get("aliases") or "")
        excerpts = _find_conversation_mentions(subject, aliases)
        if len(excerpts) < _ENRICH_MIN_CONVS:
            continue  # not enough evidence

        relations = kg.get_relations(ent["id"])
        rel_strs = [
            f"  {r['direction']}: {r['relation_type']} → {r['peer_subject']}"
            for r in relations[:10]
        ]

        old_desc = (ent.get("description") or ent.get("content") or "").strip()
        cfg = load_config()
        prompt = cfg.prompts.format(
            "dream/enrich",
            entity_type=ent.get("entity_type", "fact"),
            subject=subject,
            current_description=old_desc or "(none)",
            relationships="\n".join(rel_strs) if rel_strs else "(none)",
            conversation_excerpts="\n\n".join(f"[Excerpt {i+1}]: {x}" for i, x in enumerate(excerpts[:3])),
        )
        try:
            new_desc = run_text_completion(cfg, prompt).strip()
        except Exception:
            continue

        # Validation: must be longer, grounded, and contamination-free
        if len(new_desc) <= len(old_desc):
            continue
        # Contamination check: must not mention other entity subjects
        other_subjects = all_subjects - {subject}
        contaminated = any(
            re.search(r"\b" + re.escape(s) + r"\b", new_desc, re.IGNORECASE)
            for s in other_subjects
            if len(s) > 3
        )
        if contaminated:
            continue
        if not _ground_check(new_desc, old_desc, excerpts):
            continue

        kg.update_entity(ent["id"], new_desc)
        enriched.append({"id": ent["id"], "subject": subject})

    return enriched


# ─────────────────────────────────────────────────────────────────
# Phase 3 — Confidence decay
# ─────────────────────────────────────────────────────────────────

def _run_decay_phase() -> tuple[int, int, list[dict]]:
    """Decay confidence on old inferred relations; prune at threshold.

    Returns (decayed_count, pruned_count, details).
    """
    decayed = 0
    pruned = 0
    details: list[dict] = []
    try:
        conn = kg._get_conn()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=_DECAY_DAYS)).isoformat()
        rows = conn.execute(
            "SELECT id, confidence, source_id, target_id, relation_type "
            "FROM relations WHERE source='dream_infer' AND updated_at < ?",
            (cutoff,),
        ).fetchall()
        now_str = datetime.now(timezone.utc).isoformat()
        for row in rows:
            row = dict(row)
            new_conf = round(float(row["confidence"]) * _DECAY_FACTOR, 4)
            detail = {
                "id": row["id"],
                "relation_type": row["relation_type"],
                "old_conf": row["confidence"],
            }
            if new_conf < _PRUNE_THRESHOLD:
                conn.execute("DELETE FROM relations WHERE id = ?", (row["id"],))
                detail["action"] = "pruned"
                pruned += 1
            else:
                conn.execute(
                    "UPDATE relations SET confidence = ?, updated_at = ? WHERE id = ?",
                    (new_conf, now_str, row["id"]),
                )
                detail["new_conf"] = new_conf
                detail["action"] = "decayed"
                decayed += 1
            details.append(detail)
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("Decay phase error: %s", exc)
    return decayed, pruned, details


# ─────────────────────────────────────────────────────────────────
# Phase 4 — Relation inference
# ─────────────────────────────────────────────────────────────────

def _find_cooccurring_pairs(
    batch: list[dict],
) -> list[tuple[dict, dict, str, int]]:
    """Find entity pairs co-occurring in conversations.

    Returns list of (entity_a, entity_b, best_excerpt, co_occurrence_count).
    """
    if not batch:
        return []

    # Build per-entity regex patterns (subject + aliases)
    patterns: dict[str, re.Pattern] = {}
    for ent in batch:
        subj = (ent.get("subject") or "").strip()
        if not subj:
            continue
        aliases = [a.strip() for a in (ent.get("aliases") or "").split(",") if a.strip()]
        terms = [re.escape(subj)] + [re.escape(a) for a in aliases]
        patterns[ent["id"]] = re.compile(
            r"\b(" + "|".join(terms) + r")\b", re.IGNORECASE
        )

    entity_index = {e["id"]: e for e in batch}
    pair_excerpts: dict[str, list[str]] = {}

    try:
        threads = list_threads()
        for t in threads[:50]:
            rows = thread_conversation_rows(t.get("id", ""))
            full_text = " ".join(
                (r.get("content") or "") for r in rows if r.get("content")
            )
            if not full_text.strip():
                continue
            # Which entities appear in this thread?
            present_ids = [eid for eid, pat in patterns.items() if pat.search(full_text)]
            for i, id_a in enumerate(present_ids):
                for id_b in present_ids[i + 1:]:
                    key = _pair_key(id_a, id_b)
                    if key not in pair_excerpts:
                        pair_excerpts[key] = []
                    # Find a sentence containing both
                    parts = re.split(r"(?<=[.!?])\s+", full_text)
                    for part in parts:
                        if patterns[id_a].search(part) and patterns[id_b].search(part):
                            pair_excerpts[key].append(part[:300])
                            break
                    else:
                        pair_excerpts[key].append(f"[co-mentioned in thread {t.get('id','')}]")
    except Exception as exc:
        logger.debug("Co-occurrence scan error: %s", exc)

    # Hub cap: limit how many times any single entity appears as a pair member
    hub_counts: dict[str, int] = {}
    results: list[tuple[dict, dict, str, int]] = []

    for key, excerpts in sorted(pair_excerpts.items(), key=lambda x: -len(x[1])):
        ids = key.split("__")
        if len(ids) != 2:
            continue
        id_a, id_b = ids
        ea = entity_index.get(id_a)
        eb = entity_index.get(id_b)
        if not ea or not eb:
            continue

        # Hub cap
        if hub_counts.get(id_a, 0) >= _HUB_CAP or hub_counts.get(id_b, 0) >= _HUB_CAP:
            continue

        # Skip recently rejected pairs
        if _is_pair_recently_rejected(id_a, id_b):
            continue

        # Skip pairs where one entity description already mentions the other's name
        subj_a = (ea.get("subject") or "").strip()
        subj_b = (eb.get("subject") or "").strip()
        desc_a = (ea.get("description") or ea.get("content") or "").lower()
        desc_b = (eb.get("description") or eb.get("content") or "").lower()
        if subj_b.lower() in desc_a or subj_a.lower() in desc_b:
            continue

        # Skip pairs that already have a meaningful relation
        if kg.get_shortest_path(id_a, id_b):
            continue

        hub_counts[id_a] = hub_counts.get(id_a, 0) + 1
        hub_counts[id_b] = hub_counts.get(id_b, 0) + 1
        best_excerpt = excerpts[0] if excerpts else ""
        results.append((ea, eb, best_excerpt, len(excerpts)))

    return results[:30]


def _infer_relation(
    a: dict, b: dict, excerpt: str, co_occurrence_count: int
) -> dict | None:
    subject_a = (a.get("subject") or "").strip()
    subject_b = (b.get("subject") or "").strip()

    # Tautology guard: skip if one name is contained in the other
    if subject_a.lower() in subject_b.lower() or subject_b.lower() in subject_a.lower():
        return None

    cfg = load_config()
    prompt = cfg.prompts.format(
        "dream/infer",
        co_occurrence_count=co_occurrence_count,
        type_a=a.get("entity_type", ""),
        subject_a=subject_a,
        description_a=a.get("description", a.get("content", "")),
        type_b=b.get("entity_type", ""),
        subject_b=subject_b,
        description_b=b.get("description", b.get("content", "")),
        conversation_excerpt=excerpt or f"{subject_a} and {subject_b} are mentioned together.",
    )
    raw = run_text_completion(cfg, prompt)
    obj = kg.extract_json_block(raw, "{")
    if not obj:
        _record_rejection(a["id"], b["id"])
        return None
    try:
        data = json.loads(obj)
    except Exception:
        _record_rejection(a["id"], b["id"])
        return None

    if not data.get("has_relation"):
        _record_rejection(a["id"], b["id"])
        return None

    conf = float(data.get("confidence", 0.0))
    if conf < 0.80:
        _record_rejection(a["id"], b["id"])
        return None

    src_name = data.get("source") or ""
    tgt_name = data.get("target") or ""
    rel_type = data.get("relation_type") or ""
    evidence = data.get("evidence") or ""

    if not src_name or not tgt_name or not rel_type:
        _record_rejection(a["id"], b["id"])
        return None

    src_ent = kg.find_by_subject(None, src_name)
    tgt_ent = kg.find_by_subject(None, tgt_name)
    if not src_ent or not tgt_ent:
        _record_rejection(a["id"], b["id"])
        return None

    props = {"evidence": evidence[:200] if evidence else "", "co_occurrences": co_occurrence_count}
    rel = kg.add_relation(
        src_ent["id"], tgt_ent["id"], rel_type,
        confidence=conf,
        source="dream_infer",
        properties=props,
    )
    if not rel:
        return None

    return {
        "source_subject": src_name,
        "target_subject": tgt_name,
        "relation_type": rel_type,
        "confidence": conf,
        "evidence": evidence,
        "co_occurrences": co_occurrence_count,
    }


def _run_inference_phase(all_entities: list[dict], cfg: dict) -> list[dict]:
    """Phase 4: infer missing relations from co-occurrence analysis."""
    inferred: list[dict] = []
    batch_size = cfg.get("batch_size", 50)
    batch = all_entities[:batch_size]

    pairs = _find_cooccurring_pairs(batch)
    for ea, eb, excerpt, co_count in pairs:
        result = _infer_relation(ea, eb, excerpt, co_count)
        if result:
            inferred.append(result)
        if len(inferred) >= 10:
            break

    return inferred


# ─────────────────────────────────────────────────────────────────
# Phase 5 — System insights
# ─────────────────────────────────────────────────────────────────

def _collect_system_snapshot(summary_so_far: dict) -> str:
    lines: list[str] = ["=== System Snapshot ==="]

    # KG stats
    try:
        entities = kg.list_entities(limit=100_000)
        total = len(entities)
        rel_count = kg.count_relations()
        isolated = sum(
            1 for e in entities
            if not kg.get_relations(e["id"])
        )
        lines.append(f"KG: {total} entities, {rel_count} relations, {isolated} isolated")
    except Exception:
        lines.append("KG: stats unavailable")

    # Last extraction journal
    try:
        from .memory_extraction import _JOURNAL_FILE as _EXT_JOURNAL  # noqa: PLC0415
        if _EXT_JOURNAL.exists():
            journal = json.loads(_EXT_JOURNAL.read_text())
            if journal:
                last = journal[-1]
                lines.append(
                    f"Last extraction: {last.get('timestamp','')} — "
                    f"{last.get('threads_scanned', 0)} threads, "
                    f"{last.get('entities_saved', 0)} saved, "
                    f"{last.get('contradictions_blocked', 0)} blocked"
                )
    except Exception:
        pass

    # Last dream journal (previous cycle)
    try:
        if _JOURNAL_FILE.exists():
            journal = json.loads(_JOURNAL_FILE.read_text())
            if len(journal) >= 2:
                prev = journal[-2]
                lines.append(f"Last dream: {prev.get('timestamp','')} — {prev.get('summary','')}")
    except Exception:
        pass

    # Current dream cycle summary
    lines.append(
        f"This cycle: {len(summary_so_far.get('merges',[]))} merges, "
        f"{len(summary_so_far.get('inferred_relations',[]))} inferred, "
        f"{summary_so_far.get('decayed', 0)} decayed, "
        f"{summary_so_far.get('pruned', 0)} pruned"
    )

    # Active workflows
    try:
        from .workflow_engine import list_workflows  # noqa: PLC0415
        wfs = list_workflows()
        active = [w for w in wfs if w.get("status") in ("running", "pending")]
        if active:
            lines.append(f"Active workflows: {len(active)}")
    except Exception:
        pass

    return "\n".join(lines)


def _run_insights_phase(summary_so_far: dict) -> dict:
    """Phase 5: LLM-based health analysis of the full system."""
    try:
        snapshot = _collect_system_snapshot(summary_so_far)
        cfg = load_config()
        assistant_name = cfg.assistant_name
        prompt = cfg.prompts.format(
            "dream/insights",
            assistant_name=assistant_name,
            snapshot=snapshot,
        )
        raw = run_text_completion(cfg, prompt)
        arr_str = kg.extract_json_block(raw, "[")
        if not arr_str:
            return {"insights": []}
        insights = json.loads(arr_str)
        if not isinstance(insights, list):
            return {"insights": []}
        for ins in insights:
            logger.info(
                "Dream insight [%s/%s]: %s — %s",
                ins.get("category", "?"),
                ins.get("severity", "?"),
                ins.get("title", ""),
                ins.get("body", ""),
            )
        return {"insights": insights}
    except Exception as exc:
        logger.debug("Insights phase failed: %s", exc)
        return {"insights": [], "error": str(exc)}


# ─────────────────────────────────────────────────────────────────
# Main dream cycle
# ─────────────────────────────────────────────────────────────────

def run_dream_cycle(on_status=None) -> dict:
    cfg = _load_dream_config()
    start = datetime.now(timezone.utc)
    summary: dict[str, Any] = {
        "cycle_id": uuid.uuid4().hex[:8],
        "timestamp": start.isoformat(),
        "merges": [],
        "enriched": [],
        "decayed": 0,
        "pruned": 0,
        "decay_details": [],
        "inferred_relations": [],
        "insights": [],
        "errors": [],
    }

    all_entities = kg.list_entities(limit=100_000)
    if len(all_entities) < cfg.get("min_entities", 20):
        summary["summary"] = "Skipped: not enough entities"
        _append_journal(summary)
        return summary

    kg._skip_reindex = True
    try:
        # Phase 1 — Merge
        if on_status:
            on_status("Dream phase 1: merging duplicates…")
        summary["merges"] = _run_merge_phase(all_entities, cfg)

        # Refresh entity list after merges
        if summary["merges"]:
            all_entities = kg.list_entities(limit=100_000)

        # Phase 2 — Enrichment
        if on_status:
            on_status("Dream phase 2: enriching descriptions…")
        summary["enriched"] = _run_enrichment_phase(all_entities)

        # Phase 3 — Decay
        if on_status:
            on_status("Dream phase 3: decaying stale relations…")
        decayed, pruned, decay_details = _run_decay_phase()
        summary["decayed"] = decayed
        summary["pruned"] = pruned
        summary["decay_details"] = decay_details

        # Phase 4 — Inference
        if on_status:
            on_status("Dream phase 4: inferring new relations…")
        summary["inferred_relations"] = _run_inference_phase(all_entities, cfg)

        # Phase 5 — Insights
        if on_status:
            on_status("Dream phase 5: system insights…")
        insight_result = _run_insights_phase(summary)
        summary["insights"] = insight_result.get("insights", [])

    except Exception as exc:
        summary["errors"].append(str(exc))
        logger.exception("Dream cycle failed")
    finally:
        kg._skip_reindex = False
        try:
            kg.rebuild_index()
        except Exception as exc:
            summary["errors"].append(f"rebuild failed: {exc}")

    duration = (datetime.now(timezone.utc) - start).total_seconds()
    summary["summary"] = (
        f"{len(summary['merges'])} merge(s), "
        f"{len(summary['enriched'])} enriched, "
        f"{len(summary['inferred_relations'])} inferred, "
        f"{summary['decayed']} decayed, {summary['pruned']} pruned "
        f"in {duration:.0f}s"
    )
    summary["duration_s"] = round(duration, 1)
    _append_journal(summary)
    if on_status:
        on_status(summary["summary"])
    return summary


# ─────────────────────────────────────────────────────────────────
# Background loop
# ─────────────────────────────────────────────────────────────────

_dream_thread: threading.Thread | None = None
_dream_stop = threading.Event()


def start_dream_loop() -> None:
    global _dream_thread
    if _dream_thread and _dream_thread.is_alive():
        return
    _dream_stop.clear()

    def _loop() -> None:
        while not _dream_stop.wait(timeout=30 * 60):
            cfg = _load_dream_config()
            if _should_dream(cfg):
                run_dream_cycle()

    _dream_thread = threading.Thread(target=_loop, daemon=True, name="best-buddy-agent-dream")
    _dream_thread.start()


def stop_dream_loop() -> None:
    _dream_stop.set()
