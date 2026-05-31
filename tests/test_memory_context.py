from __future__ import annotations


def test_identity_recall_includes_name_subject(tmp_path, monkeypatch):
    from best_buddy_agent import memory
    from best_buddy_agent.memory_recall import recall_from_user_messages

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(data_dir))

    memory.save_memory("preference", "likes", "Logical reasoning")
    memory.save_memory("preference", "name", "Andrey")

    en = recall_from_user_messages(["hello", "what is my name?"], top_k=8)
    assert en.recall_path in {"semantic", "keyword", "list_recent"}
    assert "name" in en.meta["injected_subjects"]
    header = "Known facts:"
    assert "Andrey" in en.format_for_system_prompt(memory_recall_header=header)

    # Hash embeddings miss Cyrillic; list_recent fallback injects profile rows.
    ru = recall_from_user_messages(["как меня зовут?"], top_k=8)
    assert ru.recall_path == "list_recent"
    assert "Andrey" in ru.format_for_system_prompt(memory_recall_header=header)


def test_semantic_hit_avoids_list_recent_when_query_matches(tmp_path, monkeypatch):
    from best_buddy_agent import memory
    from best_buddy_agent.memory_recall import recall_from_user_messages

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(data_dir))

    memory.save_memory("fact", "User", "User enjoys storytelling")

    result = recall_from_user_messages(["User storytelling"], top_k=8)
    assert result.recall_path != "list_recent"
    assert "User" in result.format_for_system_prompt(memory_recall_header="Known facts:")
