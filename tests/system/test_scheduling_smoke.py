"""Scheduling smoke tests: agent create_reminder + scheduler notifier."""

from __future__ import annotations

import json

import pytest

from .helpers import delete_workflow, list_chat_reminder_workflows, run_chat

pytestmark = pytest.mark.system


@pytest.mark.ollama
def test_scheduling_agent_create_reminder(
    system_config,
    expectations,
    system_thread_id,
    require_workflows,
):
    sched = expectations.get("scheduling") or {}
    prompt = (sched.get("agent_prompt") or "").strip()
    msg_needle = (sched.get("reminder_message") or "BB system test ping").strip()
    if not prompt:
        pytest.skip("Set scheduling.agent_prompt in tests/system/expectations.json")

    before = {r["id"] for r in list_chat_reminder_workflows(message_substring=msg_needle)}
    reply = run_chat(system_config, prompt, thread_id=system_thread_id)
    after_rows = list_chat_reminder_workflows(message_substring=msg_needle)
    new_rows = [r for r in after_rows if r["id"] not in before]

    created_id = None
    try:
        assert new_rows, f"No chat_reminder workflow created. Agent said:\n{reply}"
        created_id = new_rows[0]["id"]
        assert new_rows[0].get("enabled") is True
        assert new_rows[0].get("notify_only") is True
    finally:
        if created_id:
            delete_workflow(created_id)


def test_scheduling_engine_fires_notifier(system_config, expectations, require_workflows):
    """Fast scheduler check without LLM — mock notifier, real workflows.db."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from best_buddy_agent import workflow_engine as wf
    from best_buddy_agent.tools import workflow_tools as wt

    sched = expectations.get("scheduling") or {}
    tz_name = system_config.deadline_watch.timezone or "UTC"
    tz = ZoneInfo(tz_name)
    fire_at = datetime.now(tz) + timedelta(seconds=90)

    wid = None
    notes: list[str] = []
    try:
        raw = wt.create_reminder_tool(
            "System test engine",
            "BB scheduler engine smoke",
            fire_at.isoformat(),
            minutes_before=0,
            timezone=tz_name,
        )
        data = json.loads(raw)
        wid = data["workflow_id"]

        past = datetime.now(tz) - timedelta(seconds=30)
        c = wf._conn()
        c.execute("UPDATE workflows SET next_run_at = ? WHERE id = ?", (past.isoformat(), wid))
        c.commit()
        c.close()

        dispatched = wf.run_scheduler_once(
            wf.default_agent_step_executor(system_config),
            notifier=notes.append,
        )
        assert dispatched >= 1, "Scheduler did not dispatch the due reminder"

        import time

        time.sleep(0.3)
        assert notes == ["BB scheduler engine smoke"]

        row = wf.get_workflow(wid)
        assert row["enabled"] is False
        runs = wf.get_run_history(wid)
        assert runs and runs[0]["status"] == "completed"
    finally:
        if wid:
            delete_workflow(wid)
