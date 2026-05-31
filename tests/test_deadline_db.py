import os
from pathlib import Path


def test_watermark_and_proposal_dedupe(tmp_path, monkeypatch):
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(tmp_path))
    from best_buddy_agent.deadline_watch import db

    db.DB_PATH  # touch module path
    import importlib

    importlib.reload(db)

    assert not db.should_skip_message("m1", "100")
    db.upsert_watermark("m1", thread_id="t1", internal_date="100", status="seen")
    assert db.should_skip_message("m1", "100")

    pid = db.create_proposal(
        message_id="m2",
        thread_id="t2",
        subject="Subj",
        sender="a@b.com",
        project="Atlas",
        summary="Submit build",
        due_at_utc="2026-06-06T17:00:00+00:00",
        confidence=0.9,
        raw_snippet="by June 6",
        ttl_hours=24,
    )
    assert db.get_proposal(pid)["status"] == "pending"
    assert db.has_pending_proposal_for_message("m2")

    assert db.record_reminder_fire(pid, "1d")
    assert not db.record_reminder_fire(pid, "1d")
