"""Tests for the extraction quality upgrades in memory_extraction.py."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────
# Alias merging during entity pass
# ─────────────────────────────────────────────────────────────────

def test_alias_merging_during_extraction():
    """Aliases from extracted entry should be written to the entity."""
    from best_buddy_agent import memory, knowledge_graph as kg
    from best_buddy_agent.memory_extraction import _dedup_and_save

    extracted = [
        {
            "category": "person",
            "subject": "Dad_AliasTest",
            "content": "Father lives in Kyiv",
            "aliases": "Father_AliasTest, Papa_AliasTest",
        }
    ]
    _dedup_and_save(extracted, source="test")
    kg.rebuild_index()

    entity = memory.find_by_subject(None, "Dad_AliasTest")
    assert entity is not None
    aliases = entity.get("aliases") or ""
    assert "Father_AliasTest" in aliases or "Papa_AliasTest" in aliases


def test_alias_enables_relation_resolution():
    """If an entity is stored as 'DadAlias2' and a relation uses alias 'FatherAlias2', it should resolve."""
    from best_buddy_agent import memory, knowledge_graph as kg
    from best_buddy_agent.memory_extraction import _dedup_and_save

    # Save entity with aliases first
    extracted_entities = [
        {
            "category": "person",
            "subject": "DadAlias2",
            "content": "Father of the narrator",
            "aliases": "FatherAlias2, PapaAlias2",
        },
        {
            "category": "person",
            "subject": "NarratorAlias2",
            "content": "The narrator of this test",
        },
    ]
    _dedup_and_save(extracted_entities, source="test")
    kg.rebuild_index()

    # Now provide a relation that references the alias 'FatherAlias2'
    extracted_with_rel = [
        {
            "relation_type": "father_of",
            "source_subject": "FatherAlias2",
            "target_subject": "NarratorAlias2",
            "confidence": 1.0,
        }
    ]
    saved, _, _ = _dedup_and_save(extracted_with_rel, source="test")
    kg.rebuild_index()

    # Check that a relation was created
    dad_entity = memory.find_by_subject(None, "DadAlias2")
    if dad_entity:
        rels = kg.get_relations(dad_entity["id"])
        has_father_of = any(r["relation_type"] == "father_of" for r in rels)
        assert has_father_of, f"Expected father_of relation, got: {[r['relation_type'] for r in rels]}"


def test_cross_source_threshold_blocks_low_sim():
    """FAISS match across document vs chat sources at 0.85 should not resolve."""
    from best_buddy_agent import memory
    from best_buddy_agent.memory_extraction import _resolve_relation_endpoint
    from best_buddy_agent import knowledge_graph as kg

    # Save entity from a document source
    entity = memory.save_memory("person", "Grandpa", "Grandfather from Ukraine", source="document:conv1")
    subject_to_id = {kg._normalize_subject("Grandpa"): entity["id"]}

    # Monkeypatch semantic_search to return a cross-source hit at 0.85 (below 0.90 threshold)
    mock_hit = {
        "id": entity["id"],
        "subject": "Grandpa",
        "source": "document:conv1",
        "score": 0.85,
    }

    with patch("best_buddy_agent.memory_extraction.kg.semantic_search", return_value=[mock_hit]):
        with patch("best_buddy_agent.memory_extraction.find_by_subject", return_value=None):
            # Source is "chat" (no document: prefix), hit source is "document:" — cross-source
            result = _resolve_relation_endpoint("Grandfather", {}, source="chat:some_thread")

    # Should be None because 0.85 < 0.90 cross-source threshold
    assert result is None


def test_cross_source_same_type_allows_lower_threshold():
    """FAISS match within same source type at 0.85 should resolve."""
    from best_buddy_agent import memory
    from best_buddy_agent.memory_extraction import _resolve_relation_endpoint
    from best_buddy_agent import knowledge_graph as kg

    entity = memory.save_memory("person", "Grandpa", "Grandfather", source="chat:c1")
    subject_to_id = {}

    mock_hit = {
        "id": entity["id"],
        "subject": "Grandpa",
        "source": "chat:c1",
        "score": 0.85,
    }

    with patch("best_buddy_agent.memory_extraction.kg.semantic_search", return_value=[mock_hit]):
        with patch("best_buddy_agent.memory_extraction.find_by_subject", return_value=None):
            result = _resolve_relation_endpoint("Grandfather", subject_to_id, source="chat:c2")

    assert result == entity["id"]


def test_workflow_threads_excluded(monkeypatch):
    """Threads with id starting 'wf-' should be skipped in run_extraction."""
    from best_buddy_agent.memory_extraction import run_extraction

    mock_threads = [
        {"id": "wf-abc123", "updated_at": "2099-01-01T00:00:00"},
        {"id": "normal-thread-1", "updated_at": "2099-01-01T00:00:00"},
    ]

    processed_threads = []

    def mock_list_threads():
        return mock_threads

    def mock_conv_rows(thread_id):
        processed_threads.append(thread_id)
        return []  # No messages → skipped in inner loop

    monkeypatch.setattr("best_buddy_agent.memory_extraction.list_threads", mock_list_threads)
    monkeypatch.setattr("best_buddy_agent.memory_extraction.thread_conversation_rows", mock_conv_rows)

    run_extraction()

    assert "wf-abc123" not in processed_threads
    assert "normal-thread-1" in processed_threads


def test_vague_relation_type_skipped():
    """Extraction entries with 'related_to' relation should not be saved."""
    from best_buddy_agent import memory, knowledge_graph as kg
    from best_buddy_agent.memory_extraction import _dedup_and_save

    # Save entities with unique names to avoid DB pollution
    a = memory.save_memory("person", "AliceVagueRel_Unique77", "Vague test entity A")
    b = memory.save_memory("person", "BobVagueRel_Unique77", "Vague test entity B")

    rels_before = kg.count_relations()
    extracted = [
        {
            "relation_type": "related_to",
            "source_subject": "AliceVagueRel_Unique77",
            "target_subject": "BobVagueRel_Unique77",
            "confidence": 1.0,
        }
    ]
    _dedup_and_save(extracted, source="test")
    kg.rebuild_index()

    rels_after = kg.count_relations()
    assert rels_after == rels_before, "Vague 'related_to' relation should not be saved"


def test_low_confidence_relation_skipped():
    """Relations with confidence < 0.80 should be skipped."""
    from best_buddy_agent import memory, knowledge_graph as kg
    from best_buddy_agent.memory_extraction import _dedup_and_save

    a = memory.save_memory("person", "AliceLowConf_Unique88", "Low conf test entity A")
    b = memory.save_memory("person", "BobLowConf_Unique88", "Low conf test entity B")

    rels_before = kg.count_relations()
    extracted = [
        {
            "relation_type": "friend_of",
            "source_subject": "AliceLowConf_Unique88",
            "target_subject": "BobLowConf_Unique88",
            "confidence": 0.5,
        }
    ]
    _dedup_and_save(extracted, source="test")
    kg.rebuild_index()
    rels_after = kg.count_relations()

    assert rels_after == rels_before, "Low-confidence relation should not be saved"


def test_contradiction_blocked_increments_counter():
    """When check_contradiction returns a conflict, the counter increments."""
    from best_buddy_agent import memory, knowledge_graph as kg
    from best_buddy_agent.memory_extraction import _dedup_and_save

    entity = memory.save_memory("fact", "ContrTestSubject_Unique99", "Born in 1960")

    with patch("best_buddy_agent.memory_extraction.check_contradiction", return_value="Different years conflict"):
        extracted = [
            {
                "category": "fact",
                "subject": "ContrTestSubject_Unique99",
                "content": "Born in 1985",
            }
        ]
        saved, contradictions, _ = _dedup_and_save(extracted, source="test")

    kg.rebuild_index()
    assert contradictions >= 1
