"""Google Calendar API client — OAuth and event helpers."""

from __future__ import annotations

import json
import logging
import os
import pathlib
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_DATA_DIR = pathlib.Path(
    os.environ.get("BEST_BUDDY_AGENT_DATA_DIR", pathlib.Path.home() / ".best_buddy_agent")
)
CALENDAR_DIR = _DATA_DIR / "calendar"
DEFAULT_CREDENTIALS_PATH = _DATA_DIR / "gmail" / "credentials.json"
DEFAULT_TOKEN_PATH = CALENDAR_DIR / "token.json"

CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]


class CalendarError(Exception):
    """Raised when Calendar is unavailable or the API call fails."""


def ensure_calendar_dir() -> None:
    CALENDAR_DIR.mkdir(parents=True, exist_ok=True)


def credentials_path(path: str | pathlib.Path | None) -> pathlib.Path:
    if path:
        p = pathlib.Path(path).expanduser()
        return p.resolve()
    return DEFAULT_CREDENTIALS_PATH.resolve()


def token_path(path: str | pathlib.Path | None) -> pathlib.Path:
    if path:
        p = pathlib.Path(path).expanduser()
        return p.resolve()
    return DEFAULT_TOKEN_PATH.resolve()


def has_credentials(credentials: str | pathlib.Path | None = None) -> bool:
    return credentials_path(credentials).is_file()


def has_token(token: str | pathlib.Path | None = None) -> bool:
    return token_path(token).is_file()


def check_token_health(token: str | pathlib.Path | None = None) -> tuple[str, str]:
    tp = token_path(token)
    if not tp.is_file():
        return ("missing", "No token file — run best-buddy-agent-calendar-auth")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(str(tp), scopes=CALENDAR_SCOPES)
        if creds.valid:
            return ("valid", "Token is valid")
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                tp.write_text(creds.to_json())
                return ("refreshed", "Token refreshed successfully")
            except Exception as exc:
                err = str(exc).lower()
                if "invalid_grant" in err or "revoked" in err:
                    return ("expired", "Refresh token revoked — re-run best-buddy-agent-calendar-auth")
                return ("error", f"Refresh failed: {exc}")
        return ("expired", "Token expired — re-run best-buddy-agent-calendar-auth")
    except Exception as exc:
        return ("error", f"Token check failed: {exc}")


def run_oauth_flow(
    *,
    credentials: str | pathlib.Path | None = None,
    token: str | pathlib.Path | None = None,
) -> pathlib.Path:
    creds_file = credentials_path(credentials)
    if not creds_file.is_file():
        raise CalendarError(f"credentials.json not found: {creds_file}")

    from google_auth_oauthlib.flow import InstalledAppFlow

    ensure_calendar_dir()
    tp = token_path(token)
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), CALENDAR_SCOPES)
    creds = flow.run_local_server(port=0)
    tp.write_text(creds.to_json())
    return tp


def build_calendar_service(
    *,
    credentials: str | pathlib.Path | None = None,
    token: str | pathlib.Path | None = None,
):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds_file = credentials_path(credentials)
    tp = token_path(token)
    if not creds_file.is_file():
        raise CalendarError(f"Calendar credentials missing: {creds_file}")
    if not tp.is_file():
        raise CalendarError("Calendar not authenticated — run best-buddy-agent-calendar-auth")

    creds = Credentials.from_authorized_user_file(str(tp), scopes=CALENDAR_SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            tp.write_text(creds.to_json())
        else:
            raise CalendarError("Calendar token invalid — re-run best-buddy-agent-calendar-auth")

    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def get_current_datetime(*, timezone: str = "UTC") -> str:
    try:
        tz = ZoneInfo(timezone)
    except Exception:
        tz = ZoneInfo("UTC")
    now = datetime.now(tz)
    return json.dumps(
        {
            "datetime": now.isoformat(),
            "timezone": timezone,
            "formatted": now.strftime("%A, %B %d, %Y %H:%M %Z"),
        },
        ensure_ascii=False,
    )


def search_events(
    service,
    *,
    min_datetime: str,
    max_datetime: str,
    max_results: int = 10,
    query: str | None = None,
) -> str:
    calendars = service.calendarList().list().execute()
    cal_data = []
    for item in calendars.get("items", []):
        cal_data.append(
            {
                "id": item["id"],
                "summary": item["summary"],
                "timeZone": item.get("timeZone", "UTC"),
            }
        )

    all_events: list[dict[str, Any]] = []
    for cal in cal_data:
        tz_name = cal.get("timeZone") or "UTC"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")
        time_min = datetime.strptime(min_datetime, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz).isoformat()
        time_max = datetime.strptime(max_datetime, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz).isoformat()
        events_result = (
            service.events()
            .list(
                calendarId=cal["id"],
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
                q=query,
            )
            .execute()
        )
        for ev in events_result.get("items", []):
            start = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))
            end = ev.get("end", {}).get("dateTime", ev.get("end", {}).get("date", ""))
            all_events.append(
                {
                    "event_id": ev.get("id", ""),
                    "calendar_id": cal["id"],
                    "summary": ev.get("summary", "(no title)"),
                    "start": start,
                    "end": end,
                    "location": ev.get("location", ""),
                    "description": ev.get("description", ""),
                    "calendar": cal["summary"],
                }
            )

    if not all_events:
        return "No events found in the specified time range."
    return json.dumps(all_events, ensure_ascii=False, indent=2)


def create_event(
    service,
    *,
    summary: str,
    start_datetime: str,
    end_datetime: str | None = None,
    timezone: str = "UTC",
    description: str = "",
    location: str = "",
    calendar_id: str = "primary",
) -> str:
    if not (summary or "").strip():
        raise CalendarError("summary is required")
    try:
        start_dt = datetime.fromisoformat(start_datetime.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CalendarError("start_datetime must be ISO 8601") from exc

    if end_datetime:
        try:
            end_dt = datetime.fromisoformat(end_datetime.replace("Z", "+00:00"))
        except ValueError as exc:
            raise CalendarError("end_datetime must be ISO 8601") from exc
    else:
        end_dt = start_dt + timedelta(hours=1)

    body: dict[str, Any] = {
        "summary": summary.strip(),
        "description": description or "",
        "location": location or "",
        "start": {"dateTime": start_dt.isoformat(), "timeZone": timezone},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": timezone},
    }
    created = service.events().insert(calendarId=calendar_id, body=body).execute()
    return json.dumps(
        {
            "event_id": created.get("id"),
            "htmlLink": created.get("htmlLink"),
            "summary": created.get("summary"),
            "start": created.get("start"),
        },
        ensure_ascii=False,
        indent=2,
    )


def update_event(
    service,
    *,
    event_id: str,
    calendar_id: str = "primary",
    summary: str | None = None,
    start_datetime: str | None = None,
    end_datetime: str | None = None,
    timezone: str = "UTC",
    description: str | None = None,
) -> str:
    eid = (event_id or "").strip()
    if not eid:
        raise CalendarError("event_id is required")
    existing = service.events().get(calendarId=calendar_id, eventId=eid).execute()
    if summary is not None:
        existing["summary"] = summary
    if description is not None:
        existing["description"] = description
    if start_datetime:
        start_dt = datetime.fromisoformat(start_datetime.replace("Z", "+00:00"))
        existing["start"] = {"dateTime": start_dt.isoformat(), "timeZone": timezone}
    if end_datetime:
        end_dt = datetime.fromisoformat(end_datetime.replace("Z", "+00:00"))
        existing["end"] = {"dateTime": end_dt.isoformat(), "timeZone": timezone}
    updated = service.events().update(calendarId=calendar_id, eventId=eid, body=existing).execute()
    return json.dumps(
        {"event_id": updated.get("id"), "summary": updated.get("summary"), "start": updated.get("start")},
        ensure_ascii=False,
        indent=2,
    )
