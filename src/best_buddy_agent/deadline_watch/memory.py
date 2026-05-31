"""Query upcoming deadlines from the knowledge graph."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .. import knowledge_graph as kg


def list_upcoming_deadlines(*, within_days: int = 7, timezone: str = "UTC") -> list[dict]:
    try:
        tz = ZoneInfo(timezone)
    except Exception:
        tz = ZoneInfo("UTC")
    now = datetime.now(tz)
    cutoff = now + timedelta(days=max(1, within_days))
    rows = kg.list_entities(entity_type="event", limit=500)
    upcoming: list[dict] = []
    for row in rows:
        props_raw = row.get("properties") or "{}"
        try:
            props = json.loads(props_raw) if isinstance(props_raw, str) else props_raw
        except json.JSONDecodeError:
            props = {}
        due_raw = props.get("due_at")
        if not due_raw:
            continue
        try:
            due = datetime.fromisoformat(str(due_raw).replace("Z", "+00:00"))
            if due.tzinfo is None:
                due = due.replace(tzinfo=tz)
        except ValueError:
            continue
        if now <= due <= cutoff and props.get("status", "active") == "active":
            upcoming.append(
                {
                    "subject": row.get("subject"),
                    "due_at": due.isoformat(),
                    "description": row.get("description"),
                    "properties": props,
                }
            )
    upcoming.sort(key=lambda x: x["due_at"])
    return upcoming
