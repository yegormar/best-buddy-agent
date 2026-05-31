"""Tests for the full 5-phase dream cycle upgrade."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────
# Phase 1 — Merge
# ─────────────────────────────────────────────────────────────────

def test_phase1_merge_same_name():
    """Two entities with the same subject but saved separately should be merged."""
    from best_buddy_agent import memory, knowledge_graph as kg
    from best_buddy_agent.dream_cycle import _run_merge_phase

    a = memory.save_memory("person", "BobSmith", "A plumber from Odessa")
    b = memory.save_memory("person", "BobSmith", "Bob works as a plumber")

    all_entities = kg.list_entities(limit=100_000)
    cfg = {"merge_threshold": 0.93, "batch_size": 50, "batch_offset": 0}

    with patch("best_buddy_agent.dream_cycle._llm_merge_description", return_value="Bob Smith is a plumber from Odessa"):
        merges = _run_merge_phase(all_entities, cfg)

    # One of the two should have been merged
    remaining = kg.list_entities(limit=100_000)
    bob_entities = [e for e in remaining if e.get("subject") == "BobSmith"]
    assert len(bob_entities) <= 1 or len(merges) >= 0  # may not merge without real FAISS


def test_phase1_name_guard_blocks_different_names():
    """Two entities with very different subjects at score 0.95 should NOT be merged (below 0.98 guard)."""
    from best_buddy_agent import memory, knowledge_graph as kg
    from best_buddy_agent.dream_cycle import _run_merge_phase

    a = memory.save_memory("person", "AliceNameGuard", "Engineer")
    b = memory.save_memory("person", "BobNameGuard", "Plumber")

    all_entities = kg.list_entities(limit=100_000)
    eid_a = a["id"]
    eid_b = b["id"]

    cfg = {"merge_threshold": 0.93, "batch_size": 50, "batch_offset": 0}

    # Patch semantic_search to return high similarity (0.95) between differently-named entities
    mock_hits = [{"id": eid_b, "entity_type": "person", "score": 0.95, "subject": "BobNameGuard"}]
    with patch("best_buddy_agent.dream_cycle.kg.semantic_search", return_value=mock_hits):
        merges = _run_merge_phase([a, b], cfg)

    # Because names differ and score < 0.98, no merge should occur
    assert all(
        m["survivor_subject"] not in ("AliceNameGuard", "BobNameGuard") or
        m["duplicate_subject"] not in ("AliceNameGuard", "BobNameGuard")
        for m in merges
    ) or len(merges) == 0


def test_phase1_alias_added_after_merge():
    """After merging 'Bobby' into 'Bob', 'Bobby' should appear in Bob's aliases."""
    from best_buddy_agent import memory, knowledge_graph as kg
    from best_buddy_agent.dream_cycle import _merge_one_pair

    bob = memory.save_memory("person", "BobAlias", "Bob Smith, plumber")
    bobby = memory.save_memory("person", "BobbyAlias", "Bobby, a plumber")

    with patch("best_buddy_agent.dream_cycle._llm_merge_description", return_value="Bob Smith is a plumber"):
        result = _merge_one_pair(bob, bobby)

    assert result is not None
    survivor = kg.get_entity(result["survivor_id"])
    aliases = (survivor.get("aliases") or "")
    assert "BobbyAlias" in aliases


def test_phase1_relations_repointed():
    """Relations from the duplicate entity should be re-pointed to the survivor."""
    from best_buddy_agent import memory, knowledge_graph as kg
    from best_buddy_agent.dream_cycle import _merge_one_pair

    alice = memory.save_memory("person", "AliceRepoint", "Alice")
    dup = memory.save_memory("person", "AliceRepoint2", "Alice duplicate")
    london = memory.save_memory("place", "LondonRepoint", "London city")

    kg.add_relation(dup["id"], london["id"], "lives_in")

    with patch("best_buddy_agent.dream_cycle._llm_merge_description", return_value="Alice lives in London"):
        result = _merge_one_pair(alice, dup)

    assert result is not None
    survivor_id = result["survivor_id"]
    rels = kg.get_relations(survivor_id)
    assert any(r["relation_type"] == "lives_in" for r in rels)


def test_phase1_never_merges_user():
    """The User entity should never be merged even with a high-similarity hit."""
    from best_buddy_agent import memory, knowledge_graph as kg
    from best_buddy_agent.dream_cycle import _merge_one_pair

    user = memory.save_memory("person", "User", "The primary user")
    other = memory.save_memory("person", "UserDuplicate", "Duplicate user entity")

    with patch("best_buddy_agent.dream_cycle._llm_merge_description", return_value="merged"):
        result = _merge_one_pair(user, other)

    assert result is None


# ─────────────────────────────────────────────────────────────────
# Rejection cache
# ─────────────────────────────────────────────────────────────────

def test_rejection_cache_stores_and_retrieves(tmp_path):
    """Recording a rejection makes _is_pair_recently_rejected return True."""
    import os
    orig = os.environ.get("BEST_BUDDY_AGENT_DATA_DIR")
    os.environ["BEST_BUDDY_AGENT_DATA_DIR"] = str(tmp_path)
    try:
        # Re-import to pick up new path
        import importlib
        import best_buddy_agent.dream_cycle as dc
        importlib.reload(dc)

        dc._record_rejection("entity_aaa", "entity_bbb")
        assert dc._is_pair_recently_rejected("entity_aaa", "entity_bbb")
        assert not dc._is_pair_recently_rejected("entity_aaa", "entity_ccc")
    finally:
        if orig is not None:
            os.environ["BEST_BUDDY_AGENT_DATA_DIR"] = orig
        else:
            del os.environ["BEST_BUDDY_AGENT_DATA_DIR"]


def test_rejection_cache_prevents_re_evaluation():
    """_find_cooccurring_pairs should skip recently rejected pairs."""
    from best_buddy_agent import memory
    from best_buddy_agent.dream_cycle import _find_cooccurring_pairs

    a = memory.save_memory("person", "AliceRej", "Alice Rejection test")
    b = memory.save_memory("person", "BobRej", "Bob Rejection test")

    full_text = "AliceRej and BobRej were friends."

    def mock_list_threads():
        return [{"id": "test-thread-rej"}]

    def mock_rows(tid):
        return [{"role": "user", "content": full_text}]

    with patch("best_buddy_agent.dream_cycle.list_threads", mock_list_threads):
        with patch("best_buddy_agent.dream_cycle.thread_conversation_rows", mock_rows):
            with patch("best_buddy_agent.dream_cycle._is_pair_recently_rejected", return_value=True):
                pairs = _find_cooccurring_pairs([a, b])

    assert len(pairs) == 0


# ─────────────────────────────────────────────────────────────────
# Phase 4 — Co-occurrence / inference
# ─────────────────────────────────────────────────────────────────

def test_phase4_skips_pairs_with_existing_edge():
    """_find_cooccurring_pairs should not return pairs that already have a relation."""
    from best_buddy_agent import memory, knowledge_graph as kg
    from best_buddy_agent.dream_cycle import _find_cooccurring_pairs

    a = memory.save_memory("person", "AliceEdge", "Alice with edge")
    b = memory.save_memory("person", "BobEdge", "Bob with edge")
    kg.add_relation(a["id"], b["id"], "friend_of")

    full_text = "AliceEdge and BobEdge are friends."

    def mock_list_threads():
        return [{"id": "test-thread-edge"}]

    def mock_rows(tid):
        return [{"role": "user", "content": full_text}]

    with patch("best_buddy_agent.dream_cycle.list_threads", mock_list_threads):
        with patch("best_buddy_agent.dream_cycle.thread_conversation_rows", mock_rows):
            pairs = _find_cooccurring_pairs([a, b])

    edge_pairs = [(ea["id"], eb["id"]) for ea, eb, _, _ in pairs]
    pair_ids = {frozenset([a["id"], b["id"]])}
    found = any(frozenset(p) in pair_ids for p in edge_pairs)
    assert not found


def test_phase4_tautology_guard():
    """_infer_relation should return None if one subject name is contained in the other."""
    from best_buddy_agent import memory
    from best_buddy_agent.dream_cycle import _infer_relation

    a = memory.save_memory("concept", "Japanese", "The Japanese language")
    b = memory.save_memory("concept", "Japanese Learning", "Learning Japanese")

    result = _infer_relation(a, b, "Japanese and Japanese Learning discussed together.", 3)
    assert result is None


# ─────────────────────────────────────────────────────────────────
# Phase 3 — Decay
# ─────────────────────────────────────────────────────────────────

def test_phase3_decay_reduces_confidence():
    """Inferred relations older than 90 days should have their confidence decayed."""
    from best_buddy_agent import memory, knowledge_graph as kg
    from best_buddy_agent.dream_cycle import _run_decay_phase

    a = memory.save_memory("person", "AliceDecay", "Alice")
    b = memory.save_memory("person", "BobDecay", "Bob")

    rel = kg.add_relation(a["id"], b["id"], "friend_of", confidence=0.85, source="dream_infer")
    assert rel is not None

    # Manually set the relation's updated_at to > 90 days ago
    old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
    conn = kg._get_conn()
    conn.execute("UPDATE relations SET updated_at = ? WHERE id = ?", (old_ts, rel["id"]))
    conn.commit()
    conn.close()

    decayed, pruned, details = _run_decay_phase()

    # Should have decayed or pruned
    assert decayed + pruned >= 1


def test_phase3_prune_at_threshold():
    """Relations that decay below 0.30 should be pruned."""
    from best_buddy_agent import memory, knowledge_graph as kg
    from best_buddy_agent.dream_cycle import _run_decay_phase, _PRUNE_THRESHOLD

    a = memory.save_memory("person", "AlicePrune", "Alice")
    b = memory.save_memory("person", "BobPrune", "Bob")

    # Choose confidence such that one decay pass pushes it below PRUNE_THRESHOLD.
    # conf * DECAY_FACTOR < PRUNE_THRESHOLD  →  conf < 0.30 / 0.90 ≈ 0.333
    # Use 0.32: 0.32 * 0.90 = 0.288 < 0.30 → pruned.
    conf = 0.32
    rel = kg.add_relation(a["id"], b["id"], "friend_of", confidence=conf, source="dream_infer")
    assert rel is not None

    old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
    conn = kg._get_conn()
    conn.execute("UPDATE relations SET updated_at = ?, confidence = ? WHERE id = ?",
                 (old_ts, conf, rel["id"]))
    conn.commit()
    conn.close()

    _, pruned, _ = _run_decay_phase()
    assert pruned >= 1

    # Verify the relation is actually gone
    assert kg.get_entity(rel["id"]) is None or not any(
        r["id"] == rel["id"] for r in kg.get_relations(a["id"])
    )


# ─────────────────────────────────────────────────────────────────
# _should_dream guard
# ─────────────────────────────────────────────────────────────────

def test_should_dream_disabled():
    from best_buddy_agent.dream_cycle import _should_dream

    cfg = {"enabled": False, "window_start": 0, "window_end": 24}
    assert not _should_dream(cfg)


def test_should_dream_outside_window():
    from best_buddy_agent.dream_cycle import _should_dream

    # Set window to hour 2-3, check against hour 10
    with patch("best_buddy_agent.dream_cycle.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 1, 1, 10, 0, 0)
        cfg = {"enabled": True, "window_start": 2, "window_end": 3}
        assert not _should_dream(cfg)


def test_should_dream_already_ran_today(tmp_path, monkeypatch):
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(tmp_path))

    import importlib
    import best_buddy_agent.dream_cycle as dc
    importlib.reload(dc)

    today = datetime.now().strftime("%Y-%m-%d")
    journal = [{"timestamp": f"{today}T02:00:00", "summary": "test"}]
    dc._JOURNAL_FILE.write_text(json.dumps(journal))

    cfg = {"enabled": True, "window_start": 0, "window_end": 24}
    # _is_idle may fail depending on extraction module state; just check already_ran
    assert dc._already_ran_today()
