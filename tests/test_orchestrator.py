from __future__ import annotations

from pathlib import Path

from pydantic_ai.models.test import TestModel

from best_buddy_agent.agent_runtime import build_agent, run_turn
from best_buddy_agent.config import load_config
from tests.conftest import write_test_conf
from best_buddy_agent.orchestrator import run_agent_once
from best_buddy_agent.threads import create_thread


def _write_conf(tmp_path: Path) -> Path:
    return write_test_conf(tmp_path, system_prompt_override="sys")


def test_orchestrator_delegates_to_run_turn(monkeypatch, tmp_path: Path):
    conf = _write_conf(tmp_path)
    cfg = load_config(str(conf))
    create_thread("t1", "test")

    calls: list[str] = []

    def fake_run_turn(*args, **kwargs):
        calls.append("run_turn")
        return "done"

    monkeypatch.setattr("best_buddy_agent.orchestrator.run_turn", fake_run_turn)
    out = run_agent_once(config=cfg, thread_id="t1", user_text="read facts")
    assert out == "done"
    assert calls == ["run_turn"]


def test_orchestrator_integration_test_model(tmp_path: Path):
    conf = _write_conf(tmp_path)
    cfg = load_config(str(conf))
    agent = build_agent(
        cfg,
        model=TestModel(call_tools=[], custom_output_text="done"),
        use_reliability=False,
    )
    create_thread("t2", "test")
    out = run_turn(cfg, "t2", "hi", _agent=agent)
    assert out == "done"
