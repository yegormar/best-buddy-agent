"""Apply approved deadline proposals — memory, calendar, reminder workflows."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from .. import knowledge_graph as kg
from .. import workflow_engine as wf
from ..config import AgentConfig
from .. import calendar_client as cc
from . import db
from .extraction import format_due_display
from .lead_times import compute_fire_at, lead_time_label

log = logging.getLogger(__name__)


def _save_deadline_memory(proposal: dict, config: AgentConfig) -> dict:
    due_at = proposal["due_at_utc"]
    props = {
        "due_at": due_at,
        "source_message_id": proposal["message_id"],
        "source_subject": proposal.get("subject") or "",
        "proposal_id": proposal["id"],
        "status": "active",
        "timezone": config.deadline_watch.timezone,
    }
    subject = proposal.get("project") or proposal.get("summary") or "Deadline"
    description = (
        f"{proposal.get('summary') or 'Deadline from email'}. "
        f"Due: {due_at}. Source: {proposal.get('sender') or ''} — "
        f"{proposal.get('subject') or ''}"
    )
    entity = kg.save_entity(
        "event",
        subject,
        description,
        properties=props,
        source="deadline_watch",
        tags="deadline,email",
    )
    project = (proposal.get("project") or "").strip()
    if project and project.lower() != subject.lower():
        project_entity = kg.save_entity(
            "project",
            project,
            f"Project referenced in email deadline: {project}",
            source="deadline_watch",
        )
        kg.add_relation(
            entity["id"],
            project_entity["id"],
            "deadline_for",
            confidence=0.9,
            source="deadline_watch",
        )
    return entity


def _create_calendar_event(proposal: dict, config: AgentConfig) -> str | None:
    if not config.calendar.is_ready():
        log.info("Calendar not ready — skipping event creation")
        return None
    try:
        service = cc.build_calendar_service(
            credentials=config.calendar.credentials_path,
            token=config.calendar.token_path,
        )
        due = datetime.fromisoformat(proposal["due_at_utc"])
        summary = f"{proposal.get('project') or 'Deadline'}: {proposal.get('summary') or 'Due'}"
        desc = (
            f"From email: {proposal.get('sender') or ''}\n"
            f"Subject: {proposal.get('subject') or ''}\n\n"
            f"{proposal.get('raw_snippet') or ''}"
        )
        result = cc.create_event(
            service,
            summary=summary,
            start_datetime=due.isoformat(),
            timezone=config.deadline_watch.timezone,
            description=desc,
        )
        data = json.loads(result)
        return data.get("event_id")
    except Exception as exc:
        log.exception("Calendar event creation failed: %s", exc)
        return None


def _schedule_reminders(proposal: dict, config: AgentConfig) -> list[str]:
    due = datetime.fromisoformat(proposal["due_at_utc"])
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    now = datetime.now(due.tzinfo)
    created: list[str] = []
    display_due = format_due_display(due, config.deadline_watch.timezone)

    for lead in config.deadline_watch.lead_times:
        try:
            fire_at = compute_fire_at(due, lead)
        except ValueError:
            continue
        if fire_at <= now:
            continue
        label = lead_time_label(lead)
        msg = (
            f"Reminder: {proposal.get('project') or proposal.get('summary') or 'Deadline'} "
            f"({label})\n"
            f"Due: {display_due}\n"
            f"From email: \"{proposal.get('subject') or ''}\" ({proposal.get('sender') or ''})\n"
            f"Excerpt: \"{(proposal.get('raw_snippet') or '')[:200]}\""
        )
        wid = wf.create_workflow(
            name=f"Reminder: {proposal.get('project') or 'deadline'} ({lead})",
            steps=[],
            schedule={"type": "once", "at": fire_at.isoformat()},
            enabled=True,
            notify_only=True,
            notify_message=msg,
            metadata={
                "kind": "deadline_reminder",
                "proposal_id": proposal["id"],
                "lead_time": lead,
                "message_id": proposal["message_id"],
            },
            allow_past_once=True,
        )
        created.append(wid)
    return created


def apply_proposal(
    proposal_id: str,
    config: AgentConfig,
    *,
    include_calendar: bool = False,
) -> dict:
    proposal = db.get_proposal(proposal_id)
    if not proposal:
        raise ValueError(f"Unknown proposal: {proposal_id}")
    if proposal["status"] != "pending":
        raise ValueError(f"Proposal {proposal_id} is not pending (status={proposal['status']})")

    entity = _save_deadline_memory(proposal, config)
    calendar_event_id = None
    if include_calendar:
        calendar_event_id = _create_calendar_event(proposal, config)
    reminder_ids = _schedule_reminders(proposal, config)

    db.update_proposal_status(proposal_id, "approved")
    db.upsert_watermark(
        proposal["message_id"],
        thread_id=proposal.get("thread_id") or "",
        status="approved",
    )

    return {
        "proposal_id": proposal_id,
        "memory_entity_id": entity.get("id"),
        "calendar_event_id": calendar_event_id,
        "reminder_workflow_ids": reminder_ids,
    }


def dismiss_proposal(proposal_id: str) -> None:
    proposal = db.get_proposal(proposal_id)
    if not proposal:
        raise ValueError(f"Unknown proposal: {proposal_id}")
    db.update_proposal_status(proposal_id, "dismissed")
    db.upsert_watermark(
        proposal["message_id"],
        thread_id=proposal.get("thread_id") or "",
        status="dismissed",
    )
