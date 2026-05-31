from __future__ import annotations

from pathlib import Path

import pytest

from best_buddy_agent import agent_runtime
from best_buddy_agent.memory_import_runner import (
    FactsPathError,
    _facts_import_status,
    build_import_user_message,
    capture_save_memory_calls,
    load_facts_import_checkpoint,
    partition_facts_files_by_checkpoint,
    record_facts_import_checkpoint,
    resolve_facts_import_paths,
    user_id_from_uploads_path,
    verify_save_records,
)
from best_buddy_agent.memory_import_runner import FactsImportResult
from best_buddy_agent.tools import memory_tools as mem_tools


def test_build_import_user_message(tmp_path: Path):
    template = tmp_path / "memory_import_turn.txt"
    template.write_text("CID={conversation_id}\n{facts_text}", encoding="utf-8")
    out = build_import_user_message(
        conversation_id="abc",
        facts_text="Facts:\n1. hello",
        prompt_template_path=template,
    )
    assert "CID=abc" in out
    assert "hello" in out


def test_capture_and_verify_save_memory(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(tmp_path / "data"))
    from tests.conftest import load_test_config

    cfg = load_test_config(tmp_path, system_prompt_override="test")

    with capture_save_memory_calls() as (saves, links):
        agent_runtime._trace_tool_invoke(
            cfg,
            "save_memory",
            {
                "category": "fact",
                "subject": "CaptureTestSubject",
                "tags": "conversation:conv1",
            },
            lambda: mem_tools.save_memory_entry(
                "fact",
                "CaptureTestSubject",
                "Was in Odessa",
                tags="conversation:conv1",
                source="document:conv1",
            ),
        )

    assert len(saves) == 1
    assert len(links) == 0
    errors = verify_save_records(
        saves,
        conversation_id="conv1",
        expected_source="document:conv1",
    )
    assert errors == []
    assert saves[0].verified_in_db
    assert saves[0].tags_include_conversation


def _write_facts(path: Path, conv_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"MERGED_CONVERSATION: {conv_id}\nFacts:\n1. test", encoding="utf-8")


def test_user_id_from_uploads_path():
    p = Path("/opt/legacy-avatar/uploads/users/01KAY2W3RC6T6R59PJJTNC4P9V/conversations")
    assert user_id_from_uploads_path(p) == "01KAY2W3RC6T6R59PJJTNC4P9V"


def test_resolve_nested_facts_file(tmp_path: Path):
    uid = "01KAY2W3RC6T6R59PJJTNC4P9V"
    cid = "01KHF48S3M06YRQ9TT9QDAV43K"
    root = tmp_path / "uploads" / "users" / uid / "conversations" / cid
    facts = root / f"{cid}_facts.txt"
    _write_facts(facts, cid)

    scope = resolve_facts_import_paths(facts)
    assert scope.user_id == uid
    assert [p.name for p in scope.facts_files] == [f"{cid}_facts.txt"]
    assert scope.conversation_ids == [cid]


def test_resolve_flat_facts_file_under_conversations(tmp_path: Path):
    uid = "01KAY2W3RC6T6R59PJJTNC4P9V"
    cid = "01KHF48S3M06YRQ9TT9QDAV43K"
    conv_dir = tmp_path / "uploads" / "users" / uid / "conversations"
    facts = conv_dir / f"{cid}_facts.txt"
    _write_facts(facts, cid)

    scope = resolve_facts_import_paths(facts)
    assert scope.user_id == uid
    assert scope.conversation_ids == [cid]


def test_resolve_all_conversations_for_user(tmp_path: Path):
    uid = "USER1"
    base = tmp_path / "uploads" / "users" / uid
    for cid in ("CONV_A", "CONV_B"):
        _write_facts(base / "conversations" / cid / f"{cid}_facts.txt", cid)

    scope = resolve_facts_import_paths(base)
    assert scope.user_id == uid
    assert sorted(scope.conversation_ids) == ["CONV_A", "CONV_B"]


def test_resolve_conversations_directory(tmp_path: Path):
    uid = "USER1"
    conv_dir = tmp_path / "uploads" / "users" / uid / "conversations"
    _write_facts(conv_dir / "C1" / "C1_facts.txt", "C1")
    _write_facts(conv_dir / "C2_facts.txt", "C2")

    scope = resolve_facts_import_paths(conv_dir)
    assert scope.user_id == uid
    assert sorted(scope.conversation_ids) == ["C1", "C2"]


def test_resolve_invalid_path_exits_with_message(tmp_path: Path):
    missing = tmp_path / "nope"
    with pytest.raises(FactsPathError, match="does not exist"):
        resolve_facts_import_paths(missing)

    empty = tmp_path / "uploads" / "users" / "U1" / "conversations"
    empty.mkdir(parents=True)
    with pytest.raises(FactsPathError, match="No \\*_facts.txt"):
        resolve_facts_import_paths(empty)


def test_resolve_rejects_non_facts_file(tmp_path: Path):
    bad = tmp_path / "readme.txt"
    bad.write_text("x", encoding="utf-8")
    with pytest.raises(FactsPathError, match="Not a facts file"):
        resolve_facts_import_paths(bad)


def test_facts_import_status_relaxed_links():
    assert _facts_import_status(
        ok_count=5,
        min_successful_saves=1,
        save_verify_failures=0,
        link_hard_failures=0,
        link_skip_count=3,
        strict_links=False,
    ) == "ok"
    assert _facts_import_status(
        ok_count=5,
        min_successful_saves=1,
        save_verify_failures=0,
        link_hard_failures=0,
        link_skip_count=3,
        strict_links=True,
    ) == "failed"
    assert _facts_import_status(
        ok_count=0,
        min_successful_saves=1,
        save_verify_failures=0,
        link_hard_failures=0,
        link_skip_count=0,
        strict_links=False,
    ) == "failed"


def test_checkpoint_skips_ok_only(tmp_path: Path):
    data_dir = tmp_path / "data"
    f1 = tmp_path / "a_facts.txt"
    f2 = tmp_path / "b_facts.txt"
    f1.touch()
    f2.touch()
    checkpoint = {
        str(f1.resolve()): {"status": "ok", "conversation_id": "a"},
        str(f2.resolve()): {"status": "partial", "conversation_id": "b"},
    }
    pending, skipped = partition_facts_files_by_checkpoint([f1, f2], checkpoint)
    assert pending == [f2]
    assert skipped == [f1]


def test_checkpoint_retries_failed(tmp_path: Path):
    f1 = tmp_path / "a_facts.txt"
    f1.touch()
    checkpoint = {str(f1.resolve()): {"status": "failed", "conversation_id": "a"}}
    pending, skipped = partition_facts_files_by_checkpoint([f1], checkpoint)
    assert pending == [f1]
    assert skipped == []


def test_checkpoint_force_ignores_done(tmp_path: Path):
    f1 = tmp_path / "a_facts.txt"
    f1.touch()
    checkpoint = {str(f1.resolve()): {"status": "ok", "conversation_id": "a"}}
    pending, skipped = partition_facts_files_by_checkpoint([f1], checkpoint, force=True)
    assert pending == [f1]
    assert skipped == []


def test_record_facts_import_checkpoint_persists(tmp_path: Path):
    data_dir = tmp_path / "data"
    facts = tmp_path / "c_facts.txt"
    facts.touch()
    result = FactsImportResult(
        conversation_id="c",
        facts_path=str(facts),
        status="ok",
        agent_reply="done",
        entity_count_before=0,
        entity_count_after=3,
        save_memory_attempts=3,
        save_memory_ok=3,
    )
    record_facts_import_checkpoint(data_dir, facts, result)
    loaded = load_facts_import_checkpoint(data_dir)
    assert loaded[str(facts.resolve())]["status"] == "ok"
    assert loaded[str(facts.resolve())]["conversation_id"] == "c"


def test_user_merge_tags_and_source_on_second_document_import(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(tmp_path / "data"))
    from best_buddy_agent import memory
    from best_buddy_agent.knowledge_graph import DOCUMENT_MULTI_SOURCE

    memory.save_memory(
        "person",
        "User",
        "First interview facts",
        tags="conversation:conv_a",
        source="document:conv_a",
    )
    memory.save_memory(
        "person",
        "User",
        "Second interview facts",
        tags="conversation:conv_b",
        source="document:conv_b",
    )
    row = memory.get_memory(memory.find_by_subject(None, "User")["id"])
    assert "conversation:conv_a" in row["tags"]
    assert "conversation:conv_b" in row["tags"]
    assert row["source"] == DOCUMENT_MULTI_SOURCE


def test_verify_user_accepts_document_multi_source(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(tmp_path / "data"))
    from best_buddy_agent import memory
    from best_buddy_agent.knowledge_graph import DOCUMENT_MULTI_SOURCE

    saved = memory.save_memory(
        "person",
        "User",
        "Narrator",
        tags="conversation:conv_x",
        source=DOCUMENT_MULTI_SOURCE,
    )
    from best_buddy_agent.memory_import_runner import SaveMemoryRecord, verify_save_records

    record = SaveMemoryRecord(category="person", subject="User", tags="conversation:conv_x")
    record.memory_id = saved["id"]
    errors = verify_save_records(
        [record],
        conversation_id="conv_x",
        expected_source="document:conv_x",
    )
    assert errors == []


def test_has_relation_normalizes_to_uses(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(tmp_path / "data"))
    from best_buddy_agent import memory
    from best_buddy_agent.tools import memory_tools as mt

    a = memory.save_memory("organisation", "Lab", "A lab")
    b = memory.save_memory("concept", "Robot", "A robot")
    result = mt.link_memories_entities("Lab", "Robot", "has")
    assert "Relationship created" in result or "already exists" in result.lower()
    rels = __import__("best_buddy_agent.knowledge_graph", fromlist=["get_relations"]).get_relations(a["id"])
    assert any(r["relation_type"] == "uses" for r in rels)


def test_same_person_link_is_skipped_not_stored(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(tmp_path / "data"))
    from best_buddy_agent import memory
    from best_buddy_agent.tools import memory_tools as mt

    a = memory.save_memory("person", "Alice", "Alice")
    b = memory.save_memory("person", "Alicia", "Alicia")
    result = mt.link_memories_entities("Alice", "Alicia", "same_person")
    assert "Link skipped" in result
    rels = __import__("best_buddy_agent.knowledge_graph", fromlist=["get_relations"]).get_relations(a["id"])
    assert not rels
