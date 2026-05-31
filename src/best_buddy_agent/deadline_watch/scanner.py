"""Inbox scan for email deadlines."""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone

from ..config import AgentConfig
from .. import gmail_client as gc
from .. import workflow_engine as wf
from . import db
from .approval import apply_proposal, dismiss_proposal
from .extraction import extract_deadline_from_email, format_due_display

log = logging.getLogger(__name__)

CALLBACK_APPROVE = "deadline:approve:"
CALLBACK_APPROVE_CAL = "deadline:approve_cal:"
CALLBACK_DISMISS = "deadline:dismiss:"


def register_scan_function() -> None:
    wf.register_workflow_function("deadline_watch.scan", _scan_function)


def _scan_function(context: dict) -> str:
    config: AgentConfig = context.get("config")
    if config is None:
        return "skipped: no config in runtime context"
    count = run_scan_once(config)
    if count == 0:
        return "silent: no new deadlines"
    return f"proposals_created:{count}"


def run_scan_once(config: AgentConfig) -> int:
    """Scan inbox and create proposals. Returns count of new proposals (0 = silent)."""
    if not config.deadline_watch.enabled:
        return 0
    if not config.gmail.is_ready():
        log.debug("Gmail not ready — skipping deadline scan")
        return 0

    db.expire_stale_proposals()

    try:
        service = gc.build_gmail_service(
            credentials=config.gmail.credentials_path,
            token=config.gmail.token_path,
        )
    except gc.GmailError as exc:
        log.warning("Deadline scan Gmail error: %s", exc)
        return 0

    query = config.deadline_watch.gmail_query
    try:
        results = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=20)
            .execute()
        )
    except Exception as exc:
        log.warning("Gmail list failed: %s", exc)
        return 0

    metas = results.get("messages") or []
    created = 0

    for meta in metas:
        mid = meta["id"]
        try:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=mid, format="full")
                .execute()
            )
        except Exception as exc:
            log.debug("Failed to fetch message %s: %s", mid, exc)
            continue

        internal_date = str(msg.get("internalDate") or "")
        if db.should_skip_message(mid, internal_date):
            continue
        if db.has_pending_proposal_for_message(mid):
            db.upsert_watermark(mid, thread_id=msg.get("threadId", ""), internal_date=internal_date)
            continue

        headers = {
            h["name"].lower(): h["value"]
            for h in msg.get("payload", {}).get("headers", [])
            if h.get("name")
        }
        body = _extract_body(msg)
        extracted = extract_deadline_from_email(
            config,
            subject=headers.get("subject", ""),
            sender=headers.get("from", ""),
            body=body,
            email_date=headers.get("date", ""),
        )

        if not extracted.has_deadline or extracted.due_at is None:
            db.upsert_watermark(mid, thread_id=msg.get("threadId", ""), internal_date=internal_date)
            continue

        due_utc = extracted.due_at.astimezone(timezone.utc)

        snippet = (extracted.quote or body or "")[:500]
        pid = db.create_proposal(
            message_id=mid,
            thread_id=msg.get("threadId", ""),
            subject=headers.get("subject", ""),
            sender=headers.get("from", ""),
            project=extracted.project,
            summary=extracted.summary,
            due_at_utc=due_utc.isoformat(),
            confidence=float(extracted.confidence),
            raw_snippet=snippet,
            ttl_hours=config.deadline_watch.proposal_ttl_hours,
        )
        send_proposal_message(config, pid)
        db.upsert_watermark(mid, thread_id=msg.get("threadId", ""), internal_date=internal_date, status="seen")
        created += 1

    return created


def _extract_body(msg: dict) -> str:
    payload = msg.get("payload", {})
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    if payload.get("parts"):
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
        for part in payload["parts"]:
            if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
    return msg.get("snippet", "")


def send_proposal_message(config: AgentConfig, proposal_id: str) -> None:
    from ..notifications.telegram_notifier import send_proactive

    proposal = db.get_proposal(proposal_id)
    if not proposal:
        return

    due = datetime.fromisoformat(proposal["due_at_utc"])
    due_display = format_due_display(due, config.deadline_watch.timezone)
    conf_pct = int(float(proposal.get("confidence") or 0) * 100)

    text = (
        "New deadline detected\n\n"
        f"Project: {proposal.get('project') or '(unnamed)'}\n"
        f"Due: {due_display}\n"
        f"From: {proposal.get('sender') or 'unknown'} — \"{proposal.get('subject') or ''}\"\n"
        f"Confidence: {conf_pct}%\n"
        f"Excerpt: \"{(proposal.get('raw_snippet') or '')[:300]}\""
    )

    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Approve reminders",
                        callback_data=f"{CALLBACK_APPROVE}{proposal_id}",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "Approve + Calendar",
                        callback_data=f"{CALLBACK_APPROVE_CAL}{proposal_id}",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "Dismiss",
                        callback_data=f"{CALLBACK_DISMISS}{proposal_id}",
                    ),
                ],
            ]
        )
        send_proactive(text, reply_markup=keyboard)
    except ImportError:
        send_proactive(text + f"\n\n(Reply: approve {proposal_id} / dismiss {proposal_id})")


def handle_deadline_callback(data: str, config: AgentConfig) -> str:
    if data.startswith(CALLBACK_APPROVE_CAL):
        pid = data[len(CALLBACK_APPROVE_CAL):]
        result = apply_proposal(pid, config, include_calendar=True)
        return (
            f"Approved with calendar.\n"
            f"Memory saved. Reminders scheduled: {len(result['reminder_workflow_ids'])}"
        )
    if data.startswith(CALLBACK_APPROVE):
        pid = data[len(CALLBACK_APPROVE):]
        result = apply_proposal(pid, config, include_calendar=False)
        return f"Reminders scheduled: {len(result['reminder_workflow_ids'])}"
    if data.startswith(CALLBACK_DISMISS):
        pid = data[len(CALLBACK_DISMISS):]
        dismiss_proposal(pid)
        return "Dismissed — won't ask again unless the thread updates."
    raise ValueError(f"Unknown deadline callback: {data}")
