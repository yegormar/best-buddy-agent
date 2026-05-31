"""Workflow management tools for the agent."""

from __future__ import annotations

import json

from .. import workflow_engine as wf


class ToolError(Exception):
    """Raised when a workflow tool fails."""


def workflow_run_status(run_id: str) -> str:
    if not run_id.strip():
        raise ToolError("run_id is required")
    state = wf.get_run_state(run_id.strip())
    if state:
        return json.dumps(state, ensure_ascii=False, default=str)
    row = wf.get_workflow(run_id.strip())
    if row:
        runs = wf.get_run_history(run_id.strip())
        if runs:
            return json.dumps(runs[0], ensure_ascii=False, default=str)
    raise ToolError(f"No run or workflow found for id: {run_id}")


def list_workflows() -> str:
    rows = wf.list_workflows()
    if not rows:
        return "No workflows configured."
    brief = []
    for r in rows:
        brief.append(
            {
                "id": r["id"],
                "name": r["name"],
                "enabled": r["enabled"],
                "schedule": r.get("schedule"),
                "notify_only": r.get("notify_only", False),
                "next_run_at": r.get("next_run_at"),
            }
        )
    return json.dumps(brief, ensure_ascii=False, indent=2)


def _normalize_schedule_dict(schedule: dict) -> dict:
    """Accept common LLM schedule mistakes."""
    s = dict(schedule)
    st = str(s.get("type") or "").strip().lower()
    if st in {"at", "datetime", "one_shot", "oneshot"}:
        s["type"] = "once"
        st = "once"
    if st == "once" and not s.get("at"):
        for key in ("time", "datetime", "when", "run_at"):
            if s.get(key):
                s["at"] = s[key]
                break
    if not s.get("type") and s.get("at"):
        s["type"] = "once"
    return s


def create_reminder_tool(
    name: str,
    message: str,
    at_datetime: str = "",
    *,
    minutes_before: int = 15,
    in_minutes: int | None = None,
    timezone: str = "UTC",
) -> str:
    """Create a one-shot notify-only reminder (Telegram when bot is running)."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(timezone)
    except Exception:
        tz = ZoneInfo("UTC")

    now = datetime.now(tz)

    if in_minutes is not None:
        fire_at = now + timedelta(minutes=max(1, int(in_minutes)))
        due = fire_at
        effective_minutes_before = 0
    else:
        raw = (at_datetime or "").strip()
        if not raw:
            raise ToolError(
                "Provide at_datetime (ISO 8601 with timezone) or in_minutes "
                "(e.g. 5 for 'remind me in 5 minutes')."
            )
        try:
            due = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ToolError(
                f"at_datetime must be ISO 8601 with timezone, not {raw!r}. "
                f"Example: 2026-05-31T14:30:00-04:00"
            ) from exc
        if due.tzinfo is None:
            due = due.replace(tzinfo=tz)
        effective_minutes_before = max(0, int(minutes_before))
        fire_at = due - timedelta(minutes=effective_minutes_before)
        now = datetime.now(fire_at.tzinfo) if fire_at.tzinfo else now

    if fire_at <= now:
        hint = ""
        if in_minutes is None and effective_minutes_before > 0 and due > now:
            hint = (
                f" Hint: use minutes_before=0 to fire at {due.isoformat()}, "
                f"or in_minutes for 'remind me in N minutes'."
            )
        raise ToolError(
            f"Reminder time {fire_at.isoformat()} is in the past (now {now.isoformat()}).{hint}"
        )

    label = (name or message or "Reminder")[:80]
    wid = wf.create_workflow(
        name=f"Reminder: {label}",
        steps=[],
        schedule={"type": "once", "at": fire_at.isoformat()},
        enabled=True,
        notify_only=True,
        notify_message=message.strip() or label,
        metadata={"kind": "chat_reminder", "due_at": due.isoformat()},
    )
    return json.dumps(
        {
            "workflow_id": wid,
            "fires_at": fire_at.isoformat(),
            "due_at": due.isoformat(),
            "minutes_before": effective_minutes_before,
            "in_minutes": in_minutes,
        },
        ensure_ascii=False,
    )


def create_workflow_tool(
    name: str,
    steps_json: str = "[]",
    schedule_json: str = "",
    notify_only: bool = False,
    notify_message: str = "",
    enabled: bool = True,
) -> str:
    try:
        steps = json.loads(steps_json or "[]")
    except json.JSONDecodeError as exc:
        raise ToolError(f"steps_json must be valid JSON: {exc}") from exc
    schedule = None
    if (schedule_json or "").strip():
        try:
            schedule = _normalize_schedule_dict(json.loads(schedule_json))
        except json.JSONDecodeError as exc:
            raise ToolError(f"schedule_json must be valid JSON: {exc}") from exc
    wid = wf.create_workflow(
        name=name.strip() or "workflow",
        steps=steps,
        schedule=schedule,
        enabled=enabled,
        notify_only=notify_only,
        notify_message=notify_message,
    )
    return json.dumps({"workflow_id": wid, "name": name})


def update_workflow_tool(
    workflow_id: str,
    name: str = "",
    steps_json: str = "",
    schedule_json: str = "",
    notify_only: bool | None = None,
    notify_message: str = "",
    enabled: bool | None = None,
) -> str:
    wid = workflow_id.strip()
    if not wf.get_workflow(wid):
        raise ToolError(f"Unknown workflow: {wid}")
    updates: dict = {}
    if name.strip():
        updates["name"] = name.strip()
    if steps_json.strip():
        try:
            updates["steps"] = json.loads(steps_json)
        except json.JSONDecodeError as exc:
            raise ToolError(f"steps_json must be valid JSON: {exc}") from exc
    if schedule_json.strip():
        try:
            updates["schedule"] = _normalize_schedule_dict(json.loads(schedule_json))
        except json.JSONDecodeError as exc:
            raise ToolError(f"schedule_json must be valid JSON: {exc}") from exc
    if notify_only is not None:
        updates["notify_only"] = notify_only
    if notify_message.strip():
        updates["notify_message"] = notify_message
    if enabled is not None:
        updates["enabled"] = enabled
    if not updates:
        raise ToolError("Provide at least one field to update")
    wf.update_workflow(wid, **updates)
    return json.dumps({"workflow_id": wid, "updated": True})


def delete_workflow_tool(workflow_id: str) -> str:
    wid = workflow_id.strip()
    if not wf.get_workflow(wid):
        raise ToolError(f"Unknown workflow: {wid}")
    wf.delete_workflow(wid)
    return json.dumps({"workflow_id": wid, "deleted": True})


def run_workflow_now(workflow_id: str) -> str:
    raise ToolError("run_workflow_now must be invoked via agent runtime")
