from __future__ import annotations

from pathlib import Path

from pydantic_ai.models.test import TestModel

from best_buddy_agent.agent_runtime import InterruptResult, build_agent, resume_turn, run_turn
from best_buddy_agent.config import load_config
from tests.conftest import write_test_conf


def _write_conf(tmp_path: Path) -> Path:
    return write_test_conf(tmp_path, system_prompt_override="sys")


def test_deferred_interrupt_without_resolver(tmp_path: Path):
    cfg = load_config(str(_write_conf(tmp_path)))
    agent = build_agent(
        cfg,
        model=TestModel(call_tools=["delete_memory"], custom_output_text="ok"),
        use_reliability=False,
    )
    out = run_turn(cfg, "def-1", "remove memory x", _agent=agent)
    assert isinstance(out, InterruptResult)
    assert out.tool_name == "delete_memory"
    assert out.message_history


def test_resume_turn_without_tool_call_id(tmp_path: Path):
    cfg = load_config(str(_write_conf(tmp_path)))
    out = resume_turn(
        cfg,
        "def-2",
        "write",
        InterruptResult(),
        approved=False,
    )
    assert out == "Nothing to resume."


def test_approval_resolver_auto_approve(tmp_path: Path):
    cfg = load_config(str(_write_conf(tmp_path)))

    def always_yes(_ctx):
        return True

    agent = build_agent(
        cfg,
        model=TestModel(call_tools=["write_file"], custom_output_text="ok"),
        use_reliability=False,
    )
    out = run_turn(
        cfg,
        "def-3",
        "go",
        approval_resolver=always_yes,
        _agent=agent,
    )
    assert isinstance(out, str)
