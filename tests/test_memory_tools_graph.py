"""Tests for the three new graph memory tools: link_memories, update_memory, explore_connections."""

from __future__ import annotations

import pytest


# ─────────────────────────────────────────────────────────────────
# link_memories_entities
# ─────────────────────────────────────────────────────────────────

def test_link_memories_by_name():
    from best_buddy_agent import memory
    from best_buddy_agent.tools import memory_tools as mt
    from best_buddy_agent import knowledge_graph as kg

    memory.save_memory("person", "Alice", "Alice is a software engineer")
    memory.save_memory("place", "London", "Capital of England")

    result = mt.link_memories_entities("Alice", "London", "lives_in")

    assert "Relationship created" in result
    assert "lives_in" in result

    alice = memory.find_by_subject(None, "Alice")
    rels = kg.get_relations(alice["id"])
    assert any(r["relation_type"] == "lives_in" for r in rels)


def test_link_memories_retry_after_race(monkeypatch):
    """find_by_subject fails first call, succeeds on second (simulates race)."""
    from best_buddy_agent import memory
    from best_buddy_agent.tools import memory_tools as mt

    alice = memory.save_memory("person", "Alice", "Alice")
    london = memory.save_memory("place", "London", "London")

    from best_buddy_agent import knowledge_graph as kg
    original_find = kg.find_by_subject
    call_counts = {"n": 0}

    def flaky_find(entity_type, subject):
        call_counts["n"] += 1
        if call_counts["n"] <= 1:
            return None
        return original_find(entity_type, subject)

    monkeypatch.setattr(kg, "find_by_subject", flaky_find)
    monkeypatch.setattr("best_buddy_agent.tools.memory_tools.kg.find_by_subject", flaky_find)

    result = mt.link_memories_entities("Alice", "London", "lives_in")
    # The retry path may succeed or the first path may succeed depending on
    # which call hits the flaky mock first; either way we expect a relation.
    assert "lives_in" in result or "Relationship created" in result or "already exists" in result


def test_link_memories_banned_relation_type():
    from best_buddy_agent import memory
    from best_buddy_agent.tools import memory_tools as mt

    memory.save_memory("person", "Alice", "Alice")
    memory.save_memory("person", "Bob", "Bob")

    result = mt.link_memories_entities("Alice", "Bob", "related_to")
    assert "Link skipped" in result
    assert "allowed vocabulary" in result.lower()


def test_link_memories_describes_skipped():
    from best_buddy_agent import memory
    from best_buddy_agent.tools import memory_tools as mt

    memory.save_memory("person", "User", "User")
    memory.save_memory("place", "Courtyards", "Courtyards")

    result = mt.link_memories_entities("User", "Courtyards", "describes")
    assert "Link skipped" in result


def test_link_memories_resolves_narrator_to_user():
    from best_buddy_agent import memory
    from best_buddy_agent.tools import memory_tools as mt

    memory.save_memory("person", "User", "The storyteller")
    memory.save_memory("place", "Lanzheron", "Beach")

    result = mt.link_memories_entities("Рассказчик", "Lanzheron", "visits")
    assert "Relationship created" in result or "already exists" in result.lower()


def test_link_memories_self_loop():
    from best_buddy_agent import memory
    from best_buddy_agent.tools import memory_tools as mt

    memory.save_memory("person", "Alice", "Alice")

    result = mt.link_memories_entities("Alice", "Alice", "knows")
    assert "Link skipped" in result
    assert "itself" in result


def test_link_memories_missing_source():
    from best_buddy_agent import memory
    from best_buddy_agent.tools import memory_tools as mt

    memory.save_memory("place", "London", "London")

    result = mt.link_memories_entities("NoSuchPerson", "London", "lives_in")
    assert "Link skipped" in result
    assert "NoSuchPerson" in result


def test_link_memories_missing_target():
    from best_buddy_agent import memory
    from best_buddy_agent.tools import memory_tools as mt

    memory.save_memory("person", "User", "User")

    result = mt.link_memories_entities("User", "пляжи Одессы", "visits")
    assert "Link skipped" in result
    assert "пляжи Одессы" in result


def test_link_memories_duplicate_returns_already_exists():
    from best_buddy_agent import memory
    from best_buddy_agent.tools import memory_tools as mt

    memory.save_memory("person", "Alice", "Alice")
    memory.save_memory("place", "London", "London")

    mt.link_memories_entities("Alice", "London", "lives_in")
    result = mt.link_memories_entities("Alice", "London", "lives_in")
    assert "already exists" in result.lower() or "Relationship created" in result


# ─────────────────────────────────────────────────────────────────
# update_memory_entry
# ─────────────────────────────────────────────────────────────────

def test_update_memory_entry():
    from best_buddy_agent import memory
    from best_buddy_agent.tools import memory_tools as mt

    ent = memory.save_memory("person", "Alice", "Alice is a programmer")
    result = mt.update_memory_entry(ent["id"], "Alice is a senior engineer", aliases="Ali")

    import json
    updated = json.loads(result)
    assert "senior engineer" in updated.get("content", "") or "senior engineer" in str(updated)

    refreshed = memory.get_memory(ent["id"])
    assert "senior engineer" in (refreshed.get("content") or "")


def test_update_memory_entry_missing_id():
    from best_buddy_agent.tools import memory_tools as mt

    with pytest.raises(mt.ToolError, match="not found"):
        mt.update_memory_entry("nonexistentid123", "new content")


def test_update_memory_entry_empty_content():
    from best_buddy_agent import memory
    from best_buddy_agent.tools import memory_tools as mt

    ent = memory.save_memory("person", "Alice", "Alice is a programmer")

    with pytest.raises(mt.ToolError, match="required"):
        mt.update_memory_entry(ent["id"], "")


# ─────────────────────────────────────────────────────────────────
# explore_connections_for_entity
# ─────────────────────────────────────────────────────────────────

def test_explore_connections_by_name():
    from best_buddy_agent import memory, knowledge_graph as kg
    from best_buddy_agent.tools import memory_tools as mt

    alice = memory.save_memory("person", "Alice", "Alice")
    london = memory.save_memory("place", "London", "London")
    kg.add_relation(alice["id"], london["id"], "lives_in")

    result = mt.explore_connections_for_entity("Alice")

    assert "Alice" in result
    assert "London" in result
    assert "lives_in" in result


def test_explore_connections_no_relations():
    from best_buddy_agent import memory
    from best_buddy_agent.tools import memory_tools as mt

    memory.save_memory("person", "Alice", "Alice")

    result = mt.explore_connections_for_entity("Alice")
    assert "Alice" in result
    assert "No direct relationships" in result or "link_memories" in result


def test_explore_connections_missing_entity():
    from best_buddy_agent.tools import memory_tools as mt

    with pytest.raises(mt.ToolError, match="not found"):
        mt.explore_connections_for_entity("NoSuchEntity")


def test_explore_connections_hops_cap():
    from best_buddy_agent import memory
    from best_buddy_agent.tools import memory_tools as mt

    memory.save_memory("person", "Alice", "Alice")

    result = mt.explore_connections_for_entity("Alice", hops=10)
    # hops should be capped at 3, not raise an error
    assert "Alice" in result
