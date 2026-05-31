"""Background memory extraction adapted from Thoth."""

from __future__ import annotations

import json
import logging
import os
import pathlib
import re
import threading
from datetime import datetime

from . import knowledge_graph as kg
from .config import load_config
from .llm_runner import run_text_completion
from .memory import VALID_CATEGORIES, find_by_subject, save_memory, update_memory
from .threads import list_threads, thread_conversation_rows
from .validation import check_contradiction

logger = logging.getLogger(__name__)

_DATA_DIR = pathlib.Path(
    os.environ.get("BEST_BUDDY_AGENT_DATA_DIR", pathlib.Path.home() / ".best_buddy_agent")
)
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_STATE_FILE = _DATA_DIR / "memory_extraction_state.json"
_JOURNAL_FILE = _DATA_DIR / "extraction_journal.json"
_JOURNAL_MAX_ENTRIES = 100

_INTERVAL_S = 2 * 3600
_active_threads: set[str] = set()
_active_lock = threading.Lock()

_VAGUE_RELATION_TYPES = {
    "related_to", "associated_with", "connected_to", "linked_to",
    "has_relation", "involves", "correlates_with",
}
_CROSS_SOURCE_THRESHOLD = 0.90
_SAME_SOURCE_THRESHOLD = 0.80
_MIN_RELATION_CONFIDENCE = 0.80


def set_active_thread(thread_id: str | None, previous_id: str | None = None) -> None:
    with _active_lock:
        if previous_id:
            _active_threads.discard(previous_id)
        if thread_id:
            _active_threads.add(thread_id)


def _load_state() -> dict:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_state(state: dict) -> None:
    _STATE_FILE.write_text(json.dumps(state, indent=2))


def _load_journal() -> list[dict]:
    if _JOURNAL_FILE.exists():
        try:
            return json.loads(_JOURNAL_FILE.read_text())
        except Exception:
            pass
    return []


def _append_journal(entry: dict) -> None:
    journal = _load_journal()
    journal.append(entry)
    if len(journal) > _JOURNAL_MAX_ENTRIES:
        journal = journal[-_JOURNAL_MAX_ENTRIES:]
    _JOURNAL_FILE.write_text(json.dumps(journal, indent=2))


def get_extraction_status() -> dict:
    st = _load_state()
    return {
        "last_extraction": st.get("last_extraction"),
        "threads_scanned": st.get("threads_scanned", 0),
        "entities_saved": st.get("entities_saved", 0),
        "interval_hours": _INTERVAL_S / 3600,
    }


def _format_conversation(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if not role or not content:
            continue
        if role == "assistant" and len(content) > 200:
            content = content[:200] + " [...]"
        lines.append(f"{role.capitalize()}: {content}")
    return "\n".join(lines)


def _extract_from_conversation(conversation_text: str) -> list[dict]:
    cfg = load_config()
    prompt = cfg.prompts.format("background/extraction", conversation=conversation_text)
    raw = run_text_completion(cfg, prompt)
    json_str = kg.extract_json_block(raw, "[")
    if not json_str:
        return []
    try:
        data = json.loads(json_str)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    valid = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if entry.get("category") and entry.get("subject") and entry.get("content"):
            valid.append(entry)
        elif entry.get("relation_type") and entry.get("source_subject") and entry.get("target_subject"):
            valid.append(entry)
    return valid


def _merge_aliases(existing: dict, new_aliases_str: str) -> None:
    """Add new_aliases_str entries to existing entity's aliases field (in-place update)."""
    if not new_aliases_str:
        return
    new_set = {a.strip() for a in new_aliases_str.split(",") if a.strip()}
    if not new_set:
        return
    existing_str = (existing.get("aliases") or "")
    existing_set = {a.strip() for a in existing_str.split(",") if a.strip()}
    merged = existing_set | new_set
    merged.discard(existing.get("subject", ""))  # don't duplicate the canonical subject
    if merged != existing_set:
        update_memory(existing["id"], existing.get("content") or "", aliases=", ".join(sorted(merged)))


def _resolve_relation_endpoint(
    name: str,
    subject_to_id: dict[str, str],
    source: str,
) -> str | None:
    """Resolve a relation endpoint name to an entity ID.

    Resolution order:
    1. subject_to_id map (populated during entity pass, includes aliases)
    2. find_by_subject exact/alias match
    3. FAISS semantic search with cross-source threshold guard
    """
    norm = kg._normalize_subject(name)
    if norm in subject_to_id:
        return subject_to_id[norm]

    found = find_by_subject(None, name)
    if found:
        return found["id"]

    try:
        hits = kg.semantic_search(name, top_k=1, threshold=_SAME_SOURCE_THRESHOLD)
        if hits:
            hit = hits[0]
            hit_source = str(hit.get("source") or "")
            is_cross_source = (
                source.startswith("document:") != hit_source.startswith("document:")
            )
            score = hit.get("score", 0.0)
            required = _CROSS_SOURCE_THRESHOLD if is_cross_source else _SAME_SOURCE_THRESHOLD
            if score >= required:
                return hit["id"]
    except Exception:
        pass

    return None


def _dedup_and_save(
    extracted: list[dict],
    source: str = "extraction",
) -> tuple[int, int, int]:
    """Process extracted entries; returns (saved_count, contradictions_blocked, low_conf_skipped)."""
    kg._skip_reindex = True
    saved_count = 0
    contradictions_blocked = 0
    low_conf_skipped = 0

    try:
        subject_to_id: dict[str, str] = {}
        user_entity = find_by_subject(None, "User")
        if user_entity:
            subject_to_id[kg._normalize_subject("User")] = user_entity["id"]

        # --- Entity pass ---
        for entry in extracted:
            category = (entry.get("category") or "").lower().strip()
            if category not in VALID_CATEGORIES:
                continue
            subject = (entry.get("subject") or "").strip()
            content = (entry.get("content") or "").strip()
            if not subject or not content:
                continue

            new_aliases = (entry.get("aliases") or "").strip()

            existing = find_by_subject(None, subject)
            if not existing:
                try:
                    hits = kg.semantic_search(f"{subject}: {content}", top_k=1, threshold=0.80)
                    if hits:
                        existing = hits[0]
                except Exception:
                    pass

            if existing:
                eid = existing["id"]
                subject_to_id[kg._normalize_subject(subject)] = eid

                # Register aliases in the resolution map so relations can use them
                all_aliases_str = (existing.get("aliases") or "")
                if new_aliases:
                    all_aliases_str = ", ".join(
                        filter(None, [all_aliases_str, new_aliases])
                    )
                    _merge_aliases(existing, new_aliases)
                    # Refresh after alias write
                    refreshed = kg.get_entity(eid)
                    if refreshed:
                        existing = refreshed
                        all_aliases_str = (existing.get("aliases") or "")

                for alias in (a.strip() for a in all_aliases_str.split(",") if a.strip()):
                    subject_to_id.setdefault(kg._normalize_subject(alias), eid)

                old_content = (existing.get("content") or "").strip()
                if content.lower() in old_content.lower():
                    continue
                if old_content.lower() in content.lower():
                    merged = content
                else:
                    conflict = check_contradiction(old_content, content, subject)
                    if conflict:
                        logger.debug("Contradiction blocked for '%s': %s", subject, conflict)
                        contradictions_blocked += 1
                        continue
                    merged = f"{old_content}. {content}".replace(". . ", ". ")
                update_memory(eid, merged)
                saved_count += 1
            else:
                res = save_memory(category, subject, content, source=source)
                new_id = res["id"]
                subject_to_id[kg._normalize_subject(subject)] = new_id
                if new_aliases:
                    _merge_aliases(res, new_aliases)
                    for alias in (a.strip() for a in new_aliases.split(",") if a.strip()):
                        subject_to_id.setdefault(kg._normalize_subject(alias), new_id)
                saved_count += 1

        # --- Relation pass ---
        for rel in [e for e in extracted if e.get("relation_type")]:
            rel_type = kg.normalize_relation_type((rel.get("relation_type") or "").strip())
            if rel_type in _VAGUE_RELATION_TYPES:
                logger.debug("Skipping vague relation type '%s'", rel_type)
                low_conf_skipped += 1
                continue

            confidence = float(rel.get("confidence") or 1.0)
            if confidence < _MIN_RELATION_CONFIDENCE:
                logger.debug(
                    "Skipping low-confidence relation '%s' (%.2f < %.2f)",
                    rel_type, confidence, _MIN_RELATION_CONFIDENCE,
                )
                low_conf_skipped += 1
                continue

            src_name = (rel.get("source_subject") or "").strip()
            tgt_name = (rel.get("target_subject") or "").strip()
            if not rel_type or not src_name or not tgt_name:
                continue

            src_id = _resolve_relation_endpoint(src_name, subject_to_id, source)
            tgt_id = _resolve_relation_endpoint(tgt_name, subject_to_id, source)

            if src_id and tgt_id and kg.add_relation(src_id, tgt_id, rel_type, source=source):
                saved_count += 1
    finally:
        kg._skip_reindex = False

    return saved_count, contradictions_blocked, low_conf_skipped


def run_extraction(on_status=None, exclude_thread_ids: set[str] | None = None) -> int:
    state = _load_state()
    last_run = state.get("last_extraction", "2000-01-01T00:00:00")
    exclude = exclude_thread_ids or set()

    threads = list_threads()
    new_threads = []
    for t in threads:
        tid = t.get("id")
        if not tid or tid in exclude:
            continue
        # Skip workflow threads — they contain AI-generated prompts, not user facts
        if tid.startswith("wf-"):
            continue
        if t.get("updated_at", "") > last_run:
            new_threads.append(t)

    total_saved = 0
    total_contradictions = 0
    total_low_conf = 0
    thread_details: list[dict] = []

    for t in new_threads:
        messages = thread_conversation_rows(t["id"])
        if not any(m.get("role") == "user" for m in messages):
            continue
        text = _format_conversation(messages)
        if len(text) > 6000:
            text = text[:6000] + "\n[... truncated]"
        extracted = _extract_from_conversation(text)
        saved, contradictions, low_conf = (0, 0, 0)
        if extracted:
            saved, contradictions, low_conf = _dedup_and_save(extracted)
        total_saved += saved
        total_contradictions += contradictions
        total_low_conf += low_conf
        thread_details.append({
            "thread": t["id"],
            "extracted": len(extracted),
            "saved": saved,
            "contradictions_blocked": contradictions,
            "low_confidence_skipped": low_conf,
        })

    try:
        if total_saved:
            kg.rebuild_index()
    except Exception as exc:
        logger.debug("rebuild index failed: %s", exc)

    now = datetime.now().isoformat()
    state["last_extraction"] = now
    state["threads_scanned"] = len(new_threads)
    state["entities_saved"] = total_saved
    _save_state(state)
    _append_journal({
        "timestamp": now,
        "threads_scanned": len(new_threads),
        "entities_saved": total_saved,
        "contradictions_blocked": total_contradictions,
        "low_confidence_skipped": total_low_conf,
        "thread_details": thread_details,
    })
    if on_status:
        on_status(f"Extraction complete: {total_saved} entities/relations saved")
    return total_saved
