import json
import os
from datetime import datetime, timedelta, timezone


def test_apply_proposal_schedules_reminders(tmp_path, monkeypatch, agent_config):
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(tmp_path))
    import importlib

    from best_buddy_agent.deadline_watch import approval, db
    from best_buddy_agent import workflow_engine as wf

    importlib.reload(db)
    importlib.reload(wf)

    due = datetime.now(timezone.utc) + timedelta(days=3)
    pid = db.create_proposal(
        message_id="msg1",
        thread_id="th1",
        subject="Deadline",
        sender="boss@co.com",
        project="Atlas",
        summary="Final delivery",
        due_at_utc=due.isoformat(),
        confidence=0.95,
        raw_snippet="due Friday",
        ttl_hours=48,
    )

    cfg = agent_config
    cfg.deadline_watch.lead_times = ("1d",)

    result = approval.apply_proposal(pid, cfg, include_calendar=False)
    assert result["memory_entity_id"]
    assert len(result["reminder_workflow_ids"]) >= 1

    workflows = wf.list_workflows()
    reminder = next(w for w in workflows if w.get("notify_only"))
    assert reminder["schedule"]["type"] == "once"

    db.update_proposal_status(pid, "pending")
    approval.dismiss_proposal(pid)
    assert db.get_proposal(pid)["status"] == "dismissed"
