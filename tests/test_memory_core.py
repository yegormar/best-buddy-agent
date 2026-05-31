def test_normalize_entity_type_aliases():
    from best_buddy_agent.knowledge_graph import normalize_entity_type

    assert normalize_entity_type("preferences") == "preference"
    assert normalize_entity_type("user_preferences") == "preference"
    assert normalize_entity_type("organizations") == "organisation"
    assert normalize_entity_type("personal") == "fact"
    assert normalize_entity_type("family") == "person"
    assert normalize_entity_type("group") == "person"


def test_save_memory_personal_category_maps_to_fact():
    from best_buddy_agent import memory

    row = memory.save_memory(
        "personal",
        "Andrey profile",
        "Born 1975-11-17; married to Olha (Olka).",
    )
    assert row["category"] == "fact"


def test_list_memories_invalid_category_message():
    from best_buddy_agent.tools import memory_tools as mt

    out = mt.list_memories(category="not_a_real_type_xyz")
    assert "Unknown category" in out
    assert "fact" in out


def test_list_memories_personal_alias_lists_fact_category():
    from best_buddy_agent.tools import memory_tools as mt

    out = mt.list_memories(category="personal")
    assert "Unknown category" not in out
    assert "[fact]" in out or "No memories" in out


def test_save_memory_entry_invalid_category_is_tool_error():
    from best_buddy_agent.tools import memory_tools as mt
    import pytest

    with pytest.raises(mt.ToolError, match="Invalid category"):
        mt.save_memory_entry("not_a_real_type_xyz", "x", "y")


def test_save_memory_plural_category():
    from best_buddy_agent import memory

    row = memory.save_memory("preferences", "Andrey", "Prefers Andriy in formal contexts")
    assert row["category"] == "preference"


def test_memory_crud_and_relations():
    from best_buddy_agent import memory, knowledge_graph

    a = memory.save_memory("person", "Alice", "Alice likes jazz")
    b = memory.save_memory("place", "London", "London city")
    assert a["id"] and b["id"]

    rel = knowledge_graph.add_relation(a["id"], b["id"], "lives_in")
    assert rel is not None

    found = memory.search_memories("Alice")
    assert any(x["subject"] == "Alice" for x in found)

    memory.update_memory(a["id"], "Alice likes jazz and tea")
    updated = memory.get_memory(a["id"])
    assert "tea" in updated["content"]


def test_save_memory_entry_document_source(monkeypatch, tmp_path):
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(tmp_path / "data"))
    from best_buddy_agent import memory
    from best_buddy_agent.tools import memory_tools as mt

    result = mt.save_memory_entry(
        "fact",
        "ImportSourceTest",
        "Imported from oral history",
        tags="conversation:conv-abc",
        source="document:conv-abc",
    )
    import json

    row = json.loads(result)
    stored = memory.get_memory(row["id"])
    assert stored["source"] == "document:conv-abc"
