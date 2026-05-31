def test_list_and_create_workflow(tmp_path, monkeypatch):
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(tmp_path))
    import importlib

    from best_buddy_agent import workflow_engine as wf
    from best_buddy_agent.tools import workflow_tools as wt

    importlib.reload(wf)

    raw = wt.list_workflows()
    assert "No workflows" in raw

    created = wt.create_workflow_tool(
        "test-wf",
        steps_json='[{"id":"s1","type":"notify","message":"hi"}]',
        schedule_json='{"type":"daily","time":"09:00"}',
    )
    assert "workflow_id" in created
    listed = wt.list_workflows()
    assert "test-wf" in listed


def test_normalize_schedule_type_at_to_once():
    from best_buddy_agent.tools.workflow_tools import _normalize_schedule_dict

    assert _normalize_schedule_dict({"type": "at", "time": "2026-05-31T14:15:00-04:00"}) == {
        "type": "once",
        "time": "2026-05-31T14:15:00-04:00",
        "at": "2026-05-31T14:15:00-04:00",
    }


def test_create_reminder_tool(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(tmp_path))
    import importlib

    from best_buddy_agent import workflow_engine as wf
    from best_buddy_agent.tools import workflow_tools as wt

    importlib.reload(wf)

    due = datetime.now(timezone.utc) + timedelta(hours=2)
    due_iso = due.isoformat()
    result = wt.create_reminder_tool("Dinner", "Prepare dinner", due_iso, minutes_before=15)
    data = __import__("json").loads(result)
    assert "workflow_id" in data
    assert data["due_at"] == due_iso
    assert data["minutes_before"] == 15

    row = wf.get_workflow(data["workflow_id"])
    assert row["notify_only"] is True
    assert row["schedule"]["type"] == "once"


def test_create_workflow_accepts_at_type(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timedelta, timezone

    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(tmp_path))
    import importlib

    from best_buddy_agent import workflow_engine as wf
    from best_buddy_agent.tools import workflow_tools as wt

    importlib.reload(wf)

    fire = datetime.now(timezone.utc) + timedelta(hours=1)
    created = wt.create_workflow_tool(
        "legacy-at",
        notify_only=True,
        notify_message="hi",
        schedule_json=json.dumps({"type": "at", "datetime": fire.isoformat()}),
    )
    data = __import__("json").loads(created)
    row = wf.get_workflow(data["workflow_id"])
    assert row["schedule"]["type"] == "once"
    assert row["schedule"]["at"] == fire.isoformat()


def test_create_reminder_in_minutes(tmp_path, monkeypatch):
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(tmp_path))
    import importlib

    from best_buddy_agent import workflow_engine as wf
    from best_buddy_agent.tools import workflow_tools as wt

    importlib.reload(wf)

    result = wt.create_reminder_tool(
        "Test",
        "Ping",
        in_minutes=5,
        timezone="America/Toronto",
    )
    data = __import__("json").loads(result)
    assert data["in_minutes"] == 5
    assert data["minutes_before"] == 0
    row = wf.get_workflow(data["workflow_id"])
    assert row["schedule"]["type"] == "once"


def test_create_reminder_at_exact_time(tmp_path, monkeypatch):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(tmp_path))
    import importlib

    from best_buddy_agent import workflow_engine as wf
    from best_buddy_agent.tools import workflow_tools as wt

    importlib.reload(wf)

    tz = ZoneInfo("America/Toronto")
    fire = datetime.now(tz) + timedelta(minutes=10)
    result = wt.create_reminder_tool(
        "Dinner",
        "Prepare dinner",
        fire.isoformat(),
        minutes_before=0,
        timezone="America/Toronto",
    )
    data = __import__("json").loads(result)
    assert data["fires_at"] == fire.isoformat()

