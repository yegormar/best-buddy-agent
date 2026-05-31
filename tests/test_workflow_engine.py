import json
from datetime import datetime, timedelta


def test_workflow_lifecycle_and_run_history():
    from best_buddy_agent import workflow_engine as wf

    wid = wf.create_workflow("daily", [{"id": "s1", "type": "prompt", "prompt": "Hello"}])
    workflows = wf.list_workflows()
    assert any(w["id"] == wid for w in workflows)

    run_id = wf.run_workflow(wid, lambda step: f"ran:{step.get('id')}")
    assert run_id

    runs = wf.get_run_history(wid)
    assert runs and runs[0]["status"] == "completed"


def test_nl_workflow_creation(monkeypatch, tmp_path):
    from best_buddy_agent import workflow_engine as wf
    from best_buddy_agent.config import AgentConfig
    from best_buddy_agent.workflow_models import WorkflowPlan, WorkflowStepSpec
    from pydantic_ai.models.test import TestModel

    plan = WorkflowPlan(
        name="morning-check",
        schedule={"type": "interval", "seconds": 60},
        steps=[
            WorkflowStepSpec(id="s1", type="prompt", prompt="Check camera status"),
            WorkflowStepSpec(id="s2", type="notify", message="Done"),
        ],
    )

    class FakeResult:
        output = plan

    monkeypatch.setattr(
        "pydantic_ai.agent.Agent.run_sync",
        lambda self, *a, **k: FakeResult(),
    )
    monkeypatch.setattr(
        "best_buddy_agent.model_factory.build_ollama_model",
        lambda config: TestModel(call_tools=[]),
    )

    from tests.conftest import load_test_config

    cfg = load_test_config(tmp_path, system_prompt_override="x")

    wid, plan = wf.create_workflow_from_natural_language(config=cfg, intent="check every minute")
    assert wid
    assert plan["name"] == "morning-check"

    saved = wf.get_workflow(wid)
    assert saved and saved["schedule"]["type"] == "interval"


def test_paused_state_and_resume():
    from best_buddy_agent import workflow_engine as wf

    wid = wf.create_workflow(
        "approval-flow",
        [
            {"id": "s1", "type": "prompt", "prompt": "draft"},
            {"id": "s2", "type": "approval", "message": "Approve?"},
            {"id": "s3", "type": "notify", "message": "ship {{step.s1.output}}"},
        ],
    )

    run_id = wf.run_workflow(wid, lambda step: "draft-ready")
    runs = wf.get_run_history(wid)
    assert runs and runs[0]["status"] == "paused"

    state = wf.get_run_state(run_id)
    assert state is not None
    assert state["status"] == "paused"
    assert state["current_step_index"] == 1

    notes = []

    def _approval(_ctx):
        return True

    wf.resume_workflow(
        run_id,
        lambda step: "unused",
        approval_resolver=_approval,
        notifier=notes.append,
    )

    runs2 = wf.get_run_history(wid)
    assert runs2 and runs2[0]["status"] == "completed"
    assert notes and "ship draft-ready" in notes[0]


def test_workflow_proof_scenario(monkeypatch, agent_config):
    """prompt → approval → prompt with agent step executor (mocked run_turn)."""
    from best_buddy_agent import workflow_engine as wf

    cfg = agent_config
    turn_calls: list[tuple[str, dict | None]] = []

    def fake_run_turn(config, thread_id, user_text, **kwargs):
        turn_calls.append((user_text, kwargs.get("workflow_context")))
        if "read" in user_text.lower():
            return "draft with memory"
        return "summary done"

    monkeypatch.setattr("best_buddy_agent.agent_runtime.run_turn", fake_run_turn)

    executor = wf.default_agent_step_executor(cfg)
    wid = wf.create_workflow(
        "proof",
        [
            {"id": "s1", "type": "prompt", "prompt": "read and search memory"},
            {"id": "s2", "type": "approval", "message": "Approve write?"},
            {"id": "s3", "type": "prompt", "prompt": "summarize {{step.s1.output}}"},
        ],
    )

    run_id = wf.run_workflow(
        wid,
        executor,
        approval_resolver=lambda _ctx: True,
    )
    assert run_id
    assert len(turn_calls) == 2
    assert "read" in turn_calls[0][0].lower()
    assert turn_calls[0][1] and turn_calls[0][1].get("workflow_id") == wid
    assert "draft with memory" in turn_calls[1][0]

    runs = wf.get_run_history(wid)
    assert runs and runs[0]["status"] == "completed"
    persisted = json.loads(runs[0].get("state_json") or "{}")
    assert persisted["step_outputs"]["s3"] == "summary done"


def test_scheduler_dispatches_due_workflow():
    from best_buddy_agent import workflow_engine as wf

    wid = wf.create_workflow(
        "polling",
        [{"id": "s1", "type": "prompt", "prompt": "ping"}],
        schedule={"type": "interval", "seconds": 1},
        enabled=True,
    )

    # Force due now to avoid sleeping in test
    c = wf._conn()
    c.execute(
        "UPDATE workflows SET next_run_at = ? WHERE id = ?",
        ((datetime.now() - timedelta(seconds=1)).isoformat(), wid),
    )
    c.commit()
    c.close()

    calls = []

    def _exec(step):
        calls.append(step.get("id"))
        return "ok"

    dispatched = wf.run_scheduler_once(_exec)
    assert dispatched >= 1

    # give background thread a moment
    import time

    time.sleep(0.2)

    runs = wf.get_run_history(wid)
    assert runs and runs[0]["status"] in {"completed", "running"}
