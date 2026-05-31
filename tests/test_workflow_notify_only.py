from datetime import datetime, timedelta


def test_notify_only_workflow(tmp_path, monkeypatch):
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(tmp_path))
    import importlib

    from best_buddy_agent import workflow_engine as wf

    importlib.reload(wf)

    notes: list[str] = []
    fire_at = (datetime.now() + timedelta(hours=1)).isoformat()
    wid = wf.create_workflow(
        "reminder",
        steps=[],
        schedule={"type": "once", "at": fire_at},
        notify_only=True,
        notify_message="Ping!",
    )
    run_id = wf.run_workflow(wid, lambda s: "", notifier=notes.append)
    assert run_id
    assert notes == ["Ping!"]

    row = wf.get_workflow(wid)
    assert row["enabled"] is False


def test_function_step(tmp_path, monkeypatch):
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(tmp_path))
    import importlib

    from best_buddy_agent import workflow_engine as wf

    importlib.reload(wf)
    wf.register_workflow_function("test.fn", lambda ctx: f"ok:{ctx.get('workflow_id')}")

    wid = wf.create_workflow(
        "fn",
        [{"id": "s1", "type": "function", "name": "test.fn"}],
    )
    out = wf.run_workflow(wid, lambda s: "")
    runs = wf.get_run_history(wid)
    assert runs[0]["status"] == "completed"
    assert "ok:" in runs[0]["output"]
