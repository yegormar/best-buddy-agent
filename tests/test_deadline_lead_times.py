from datetime import datetime, timedelta

from best_buddy_agent.deadline_watch.lead_times import compute_fire_at, parse_lead_time


def test_parse_lead_time():
    assert parse_lead_time("1d") == timedelta(days=1)
    assert parse_lead_time("1h") == timedelta(hours=1)
    assert parse_lead_time("0d") == timedelta(days=0)


def test_compute_fire_at():
    due = datetime(2026, 6, 6, 17, 0, 0)
    fire = compute_fire_at(due, "1d")
    assert fire == datetime(2026, 6, 5, 17, 0, 0)
