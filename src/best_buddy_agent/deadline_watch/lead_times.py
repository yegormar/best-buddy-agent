"""Parse lead time offsets like 1d, 0d, 1h."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

_LEAD_RE = re.compile(r"^(\d+)([dhm])$", re.IGNORECASE)


def parse_lead_time(spec: str) -> timedelta:
    s = (spec or "").strip().lower()
    m = _LEAD_RE.match(s)
    if not m:
        raise ValueError(f"Invalid lead time: {spec!r} (use e.g. 1d, 0d, 1h)")
    amount = int(m.group(1))
    unit = m.group(2)
    if unit == "d":
        return timedelta(days=amount)
    if unit == "h":
        return timedelta(hours=amount)
    return timedelta(minutes=amount)


def lead_time_label(spec: str) -> str:
    try:
        delta = parse_lead_time(spec)
    except ValueError:
        return spec
    if delta.days == 1 and delta.seconds == 0:
        return "1 day before"
    if delta.days == 0 and delta.seconds == 0:
        return "at due time"
    if delta.total_seconds() == 3600:
        return "1 hour before"
    if delta.days:
        return f"{delta.days} day(s) before"
    hours = int(delta.total_seconds() // 3600)
    if hours:
        return f"{hours} hour(s) before"
    minutes = int(delta.total_seconds() // 60)
    return f"{minutes} minute(s) before"


def compute_fire_at(due_at: datetime, lead_spec: str) -> datetime:
    return due_at - parse_lead_time(lead_spec)
