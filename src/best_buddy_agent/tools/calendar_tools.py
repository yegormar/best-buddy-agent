"""Google Calendar tools for Best Buddy agent."""

from __future__ import annotations

from ..config import AgentConfig
from .. import calendar_client as cc


class ToolError(Exception):
    """Raised when a Calendar tool cannot run."""


def _require_service(config: AgentConfig):
    if not config.calendar.enabled:
        raise ToolError("Calendar is disabled — set [calendar] enabled = true in config")
    try:
        return cc.build_calendar_service(
            credentials=config.calendar.credentials_path,
            token=config.calendar.token_path,
        )
    except cc.CalendarError as exc:
        raise ToolError(str(exc)) from exc


def get_current_datetime(config: AgentConfig) -> str:
    return cc.get_current_datetime(timezone=config.deadline_watch.timezone)


def search_events(
    config: AgentConfig,
    min_datetime: str,
    max_datetime: str,
    max_results: int = 10,
    query: str = "",
) -> str:
    service = _require_service(config)
    try:
        return cc.search_events(
            service,
            min_datetime=min_datetime,
            max_datetime=max_datetime,
            max_results=max_results,
            query=query or None,
        )
    except cc.CalendarError as exc:
        raise ToolError(str(exc)) from exc


def create_calendar_event(
    config: AgentConfig,
    summary: str,
    start_datetime: str,
    end_datetime: str = "",
    description: str = "",
    location: str = "",
    calendar_id: str = "primary",
) -> str:
    service = _require_service(config)
    try:
        return cc.create_event(
            service,
            summary=summary,
            start_datetime=start_datetime,
            end_datetime=end_datetime or None,
            timezone=config.deadline_watch.timezone,
            description=description,
            location=location,
            calendar_id=calendar_id,
        )
    except cc.CalendarError as exc:
        raise ToolError(str(exc)) from exc


def update_calendar_event(
    config: AgentConfig,
    event_id: str,
    summary: str = "",
    start_datetime: str = "",
    end_datetime: str = "",
    description: str = "",
    calendar_id: str = "primary",
) -> str:
    service = _require_service(config)
    try:
        return cc.update_event(
            service,
            event_id=event_id,
            calendar_id=calendar_id,
            summary=summary or None,
            start_datetime=start_datetime or None,
            end_datetime=end_datetime or None,
            timezone=config.deadline_watch.timezone,
            description=description or None,
        )
    except cc.CalendarError as exc:
        raise ToolError(str(exc)) from exc


def calendar_status(config: AgentConfig) -> str:
    cal = config.calendar
    lines = [
        f"enabled: {cal.enabled}",
        f"credentials: {cal.credentials_path} ({'ok' if cal.credentials_path.is_file() else 'missing'})",
        f"token: {cal.token_path} ({'ok' if cal.token_path.is_file() else 'missing'})",
    ]
    if cal.token_path.is_file():
        status, detail = cc.check_token_health(cal.token_path)
        lines.append(f"token_health: {status} — {detail}")
    return "\n".join(lines)
