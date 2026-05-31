from __future__ import annotations

from pathlib import Path

from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models.test import TestModel

from best_buddy_agent.agent_runtime import InterruptResult, build_agent, resume_turn, run_turn
from best_buddy_agent.config import load_config
from tests.conftest import write_test_conf
from best_buddy_agent.exceptions import AgentEmptyResponseError
from best_buddy_agent.memory_recall import recall_memories
from best_buddy_agent.threads import append_turn_messages, load_thread_message_history, thread_conversation_rows


def _write_conf(tmp_path: Path) -> Path:
    return write_test_conf(tmp_path, system_prompt_override="sys")


def test_resume_turn_passes_message_history(monkeypatch, tmp_path: Path):
    cfg = load_config(str(_write_conf(tmp_path)))
    captured: list = []

    def fake_run_turn(*_args, **kwargs):
        captured.append(kwargs.get("message_history"))
        return "resumed"

    monkeypatch.setattr("best_buddy_agent.agent_runtime.run_turn", fake_run_turn)
    history = [ModelRequest(parts=[UserPromptPart(content="prior")])]
    out = resume_turn(
        cfg,
        "t-resume",
        "user",
        InterruptResult(tool_call_id="call-1", message_history=history),
        approved=True,
    )
    assert out == "resumed"
    assert captured[0] == history


def test_thread_message_batches_round_trip(tmp_path: Path):
    history = [ModelRequest(parts=[UserPromptPart(content="stored")])]
    append_turn_messages("batch-thread", history)
    loaded = load_thread_message_history("batch-thread")
    assert len(loaded) == 1
    rows = thread_conversation_rows("batch-thread")
    assert rows[0]["role"] == "user"
    assert rows[0]["content"] == "stored"


def test_empty_model_output_raises(tmp_path: Path):
    from pydantic_ai.exceptions import UnexpectedModelBehavior

    cfg = load_config(str(_write_conf(tmp_path)))
    agent = build_agent(
        cfg,
        model=TestModel(call_tools=[], custom_output_text=""),
        use_reliability=False,
    )
    try:
        run_turn(cfg, "empty-1", "hi", _agent=agent)
        assert False, "expected empty-output failure"
    except (AgentEmptyResponseError, UnexpectedModelBehavior):
        pass


def test_memory_recall_single_path(tmp_path, monkeypatch):
    from best_buddy_agent import memory

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(data_dir))
    memory.save_memory("preference", "name", "Andrey")

    inject = recall_memories("what is my name?", top_k=8)
    tool = recall_memories("what is my name?", top_k=8)
    assert inject.memories
    header = "Known facts:"
    assert "Andrey" in inject.format_for_system_prompt(memory_recall_header=header)
    assert "Andrey" in tool.format_for_tool()
    assert inject.meta["recall_path"] != "none"
