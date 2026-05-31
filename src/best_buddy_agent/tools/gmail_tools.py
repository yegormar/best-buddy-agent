"""Gmail tools for the Best Buddy agent (read + drafts only)."""

from __future__ import annotations

from pathlib import Path

from ..config import AgentConfig
from .. import gmail_client as gc


class ToolError(Exception):
    """Raised when a Gmail tool cannot run."""


def _require_service(config: AgentConfig):
    if not config.gmail.enabled:
        raise ToolError("Gmail is disabled — set [gmail] enabled = true in config")
    try:
        return gc.build_gmail_service(
            credentials=config.gmail.credentials_path,
            token=config.gmail.token_path,
        )
    except gc.GmailError as exc:
        raise ToolError(str(exc)) from exc


def search_gmail(config: AgentConfig, query: str, max_results: int = 10) -> str:
    service = _require_service(config)
    try:
        return gc.search_messages(service, query, max_results=max_results)
    except gc.GmailError as exc:
        raise ToolError(str(exc)) from exc


def get_gmail_message(config: AgentConfig, message_id: str) -> str:
    service = _require_service(config)
    try:
        return gc.get_message(service, message_id)
    except gc.GmailError as exc:
        raise ToolError(str(exc)) from exc


def get_gmail_thread(config: AgentConfig, thread_id: str) -> str:
    service = _require_service(config)
    try:
        return gc.get_thread(service, thread_id)
    except gc.GmailError as exc:
        raise ToolError(str(exc)) from exc


def create_gmail_draft(
    config: AgentConfig,
    message: str,
    to: str,
    subject: str,
    cc: str = "",
    bcc: str = "",
    attachments: str = "",
) -> str:
    service = _require_service(config)
    try:
        return gc.create_draft(
            service,
            message=message,
            to=to,
            subject=subject,
            cc=cc,
            bcc=bcc,
            attachments=attachments,
            files_root=config.files_root,
        )
    except gc.GmailError as exc:
        raise ToolError(str(exc)) from exc


def gmail_status(config: AgentConfig) -> str:
    """Human-readable Gmail setup status (for CLI)."""
    g = config.gmail
    lines = [
        f"enabled: {g.enabled}",
        f"credentials: {g.credentials_path} ({'ok' if g.credentials_path.is_file() else 'missing'})",
        f"token: {g.token_path} ({'ok' if g.token_path.is_file() else 'missing'})",
    ]
    if g.enabled and g.credentials_path.is_file() and g.token_path.is_file():
        status, detail = gc.check_token_health(g.token_path)
        lines.append(f"token_health: {status} — {detail}")
    return "\n".join(lines)
