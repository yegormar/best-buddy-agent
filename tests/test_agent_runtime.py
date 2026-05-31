from __future__ import annotations

from pathlib import Path

from pydantic_ai.models.test import TestModel

from best_buddy_agent.agent_runtime import build_agent, run_turn
from best_buddy_agent.config import load_config
from tests.conftest import write_test_conf
from best_buddy_agent.tools import filesystem as fs


def _write_conf(tmp_path: Path) -> Path:
    return write_test_conf(tmp_path, system_prompt_override="sys")


def test_run_turn_with_test_model(tmp_path: Path):
    cfg = load_config(str(_write_conf(tmp_path)))
    agent = build_agent(
        cfg,
        model=TestModel(call_tools=[], custom_output_text="hello back"),
        use_reliability=False,
    )
    out = run_turn(cfg, "rt-1", "hi", _agent=agent)
    assert out == "hello back"


def test_read_file_tool_direct(tmp_path: Path):
    cfg = load_config(str(_write_conf(tmp_path)))
    target = tmp_path / "via_tool.txt"
    target.write_text("tool ok", encoding="utf-8")
    out = fs.read_file(cfg, str(target.name))
    assert "tool ok" in out


def test_trace_tool_invoke_returns_tool_error_message(tmp_path: Path):
    from best_buddy_agent import agent_runtime

    cfg = load_config(str(_write_conf(tmp_path)))
    out = agent_runtime._trace_tool_invoke(
        cfg,
        "read_file",
        {"path": ""},
        lambda: fs.read_file(cfg, ""),
    )
    assert out == "path is required"
