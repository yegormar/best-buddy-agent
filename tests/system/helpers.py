"""Shared helpers for live system smoke tests."""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from best_buddy_agent.agent_runtime import InterruptResult
from best_buddy_agent.approval import fixed_approval_resolver
from best_buddy_agent.config import AgentConfig, load_config
from best_buddy_agent.runtime import chat_once

SYSTEM_DIR = Path(__file__).resolve().parent
ROOT = SYSTEM_DIR.parents[1]


def default_conf_path() -> Path:
    env = (os.environ.get("BEST_BUDDY_AGENT_CONF") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (ROOT / "conf" / "best_buddy_agent.conf").resolve()


def load_system_config() -> AgentConfig:
    path = default_conf_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"Config not found: {path}. Set BEST_BUDDY_AGENT_CONF or create conf/best_buddy_agent.conf"
        )
    return load_config(str(path))


def load_expectations() -> dict[str, Any]:
    for name in ("expectations.json", "expectations.local.json"):
        path = SYSTEM_DIR / name
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    example = SYSTEM_DIR / "expectations.example.json"
    raise FileNotFoundError(
        f"Copy {example.name} to expectations.json and edit values for your account."
    )


def new_thread_id(prefix: str = "system-test") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def run_chat(
    config: AgentConfig,
    user_text: str,
    *,
    thread_id: str | None = None,
    auto_approve: bool = True,
) -> str:
    """Run one user turn; auto-approve deferred tools when requested."""
    tid = thread_id or new_thread_id()
    resolver = fixed_approval_resolver(True) if auto_approve else None
    reply = chat_once(
        config=config,
        thread_id=tid,
        user_text=user_text,
        timeout_sec=int(os.environ.get("BEST_BUDDY_AGENT_SYSTEM_TEST_TIMEOUT", "180")),
        approval_resolver=resolver,
    )
    if isinstance(reply, InterruptResult):
        raise AssertionError(
            f"Unexpected approval interrupt for {reply.tool_name!r}. "
            "Re-run with auto_approve=True or approve manually."
        )
    text = str(reply).strip()
    if not text:
        raise AssertionError("Agent returned an empty response")
    return text


def response_contains(text: str, needle: str) -> bool:
    return needle.lower() in text.lower()


def response_contains_any(text: str, needles: list[str]) -> list[str]:
    missing = [n for n in needles if not response_contains(text, n)]
    return missing


def extract_first_number(text: str) -> str | None:
    m = re.search(r"\b(\d{1,3})\b", text)
    return m.group(1) if m else None


def gmail_service(config: AgentConfig):
    from best_buddy_agent import gmail_client as gc

    if not config.gmail.is_ready():
        raise RuntimeError("Gmail not ready — enable [gmail] and run best-buddy-agent-gmail-auth")
    return gc.build_gmail_service(
        credentials=config.gmail.credentials_path,
        token=config.gmail.token_path,
    )


def find_draft_ids_by_subject(config: AgentConfig, subject: str) -> list[str]:
    service = gmail_service(config)
    q = f'in:drafts subject:"{subject}"'
    result = service.users().drafts().list(userId="me", q=q, maxResults=10).execute()
    drafts = result.get("drafts") or []
    return [d["id"] for d in drafts if d.get("id")]


def delete_drafts_by_subject(config: AgentConfig, subject: str) -> int:
    service = gmail_service(config)
    deleted = 0
    for draft_id in find_draft_ids_by_subject(config, subject):
        service.users().drafts().delete(userId="me", id=draft_id).execute()
        deleted += 1
    return deleted


def list_chat_reminder_workflows(*, message_substring: str = "") -> list[dict[str, Any]]:
    from best_buddy_agent import workflow_engine as wf

    rows = wf.list_workflows()
    out: list[dict[str, Any]] = []
    for row in rows:
        meta = row.get("metadata") or {}
        if meta.get("kind") != "chat_reminder":
            continue
        msg = row.get("notify_message") or ""
        if message_substring and message_substring.lower() not in msg.lower():
            continue
        out.append(row)
    return out


def delete_workflow(workflow_id: str) -> None:
    from best_buddy_agent import workflow_engine as wf

    if wf.get_workflow(workflow_id):
        wf.delete_workflow(workflow_id)
