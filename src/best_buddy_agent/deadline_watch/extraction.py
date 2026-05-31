"""Structured deadline extraction from email content."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from ..config import AgentConfig
from ..model_factory import build_ollama_model, build_thinking_capabilities

log = logging.getLogger(__name__)

EXTRACTION_SYSTEM = """You extract project deadlines from email text.
Return structured JSON only via the schema.
Rules:
- Set has_deadline=false unless there is a concrete date or unambiguous relative date.
- Ignore vague phrases like "soon" or "ASAP" without a date anchor.
- Resolve relative dates (e.g. "by Friday", "EOD tomorrow") using the provided current datetime and timezone.
- project: short name of the project or deliverable.
- confidence: 0.0-1.0 how sure you are this is a real deadline for the user.
- quote: short excerpt supporting the deadline.
"""


class ExtractedDeadline(BaseModel):
    has_deadline: bool = False
    project: str = ""
    summary: str = ""
    due_at: datetime | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    quote: str = ""


def extract_deadline_from_email(
    config: AgentConfig,
    *,
    subject: str,
    sender: str,
    body: str,
    email_date: str = "",
) -> ExtractedDeadline:
    try:
        tz = ZoneInfo(config.deadline_watch.timezone)
    except Exception:
        tz = ZoneInfo("UTC")
    now = datetime.now(tz)

    prompt = (
        f"Current datetime ({config.deadline_watch.timezone}): {now.isoformat()}\n"
        f"Email date header: {email_date or 'unknown'}\n"
        f"From: {sender}\n"
        f"Subject: {subject}\n\n"
        f"Body:\n{(body or '')[:12000]}"
    )

    llm = build_ollama_model(config)
    agent = Agent(
        llm,
        output_type=ExtractedDeadline,
        instructions=EXTRACTION_SYSTEM,
        capabilities=build_thinking_capabilities(config),
    )
    try:
        result = agent.run_sync(prompt)
        extracted: ExtractedDeadline = result.output
        if extracted.due_at and extracted.due_at.tzinfo is None:
            extracted.due_at = extracted.due_at.replace(tzinfo=tz)
        return extracted
    except Exception as exc:
        log.warning("Deadline extraction failed: %s", exc)
        return ExtractedDeadline(has_deadline=False)


def format_due_display(due_at: datetime, timezone: str) -> str:
    try:
        tz = ZoneInfo(timezone)
        local = due_at.astimezone(tz)
    except Exception:
        local = due_at
    return local.strftime("%a %d %b %Y %H:%M %Z")
