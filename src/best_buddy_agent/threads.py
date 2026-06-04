"""Thread persistence via pydantic-ai message batches (canonical history)."""

from __future__ import annotations

import os
import pathlib
import sqlite3
from collections.abc import Sequence
from datetime import datetime

from pydantic_ai.messages import (
    BinaryContent,
    ImageUrl,
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserContent,
    UserPromptPart,
)

_DATA_DIR = pathlib.Path(
    os.environ.get("BEST_BUDDY_AGENT_DATA_DIR", pathlib.Path.home() / ".best_buddy_agent")
)
_DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = _DATA_DIR / "threads.db"
_MESSAGES_ADAPTER = ModelMessagesTypeAdapter


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS threads (id TEXT PRIMARY KEY, name TEXT, created_at TEXT, updated_at TEXT)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS thread_message_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT NOT NULL,
            messages_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    return conn


def create_thread(thread_id: str, name: str = "") -> None:
    now = datetime.now().isoformat()
    c = _conn()
    c.execute(
        "INSERT OR IGNORE INTO threads (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (thread_id, name, now, now),
    )
    c.commit()
    c.close()


def append_turn_messages(thread_id: str, messages: list[ModelMessage]) -> None:
    """Persist new messages from one agent run (`result.new_messages()`)."""
    if not messages:
        return
    create_thread(thread_id)
    payload = _MESSAGES_ADAPTER.dump_json(messages).decode("utf-8")
    now = datetime.now().isoformat()
    c = _conn()
    c.execute(
        "INSERT INTO thread_message_batches (thread_id, messages_json, created_at) VALUES (?, ?, ?)",
        (thread_id, payload, now),
    )
    c.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (now, thread_id))
    c.commit()
    c.close()


def user_prompt_content_text(content: str | Sequence[UserContent]) -> str:
    """Flatten user prompt for context, memory, and trace (no binary payloads)."""
    if isinstance(content, str):
        return (content or "").strip()
    if not content:
        return ""
    lines: list[str] = []
    for item in content:
        if isinstance(item, str):
            text = item.strip()
            if text:
                lines.append(text)
        elif isinstance(item, (ImageUrl, BinaryContent)):
            lines.append("[image]")
        else:
            text = str(item).strip()
            if text:
                lines.append(text)
    return "\n".join(lines).strip()


def load_thread_message_history(thread_id: str) -> list[ModelMessage]:
    """Load full pydantic-ai history for a thread."""
    c = _conn()
    batches = c.execute(
        "SELECT messages_json FROM thread_message_batches WHERE thread_id = ? ORDER BY id",
        (thread_id,),
    ).fetchall()
    c.close()
    history: list[ModelMessage] = []
    for row in batches:
        history.extend(_MESSAGES_ADAPTER.validate_json(row["messages_json"]))
    return history


def thread_conversation_rows(thread_id: str) -> list[dict[str, str]]:
    """Derive role/content rows from canonical history (context + extraction)."""
    rows: list[dict[str, str]] = []
    for msg in load_thread_message_history(thread_id):
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    content = user_prompt_content_text(part.content)
                    if content:
                        rows.append({"role": "user", "content": content})
        elif isinstance(msg, ModelResponse):
            parts_text: list[str] = []
            for part in msg.parts:
                if isinstance(part, TextPart):
                    parts_text.append(part.content or "")
            content = "".join(parts_text).strip()
            if content:
                rows.append({"role": "assistant", "content": content})
    return rows


def list_threads() -> list[dict]:
    c = _conn()
    rows = c.execute("SELECT id, name, created_at, updated_at FROM threads ORDER BY updated_at DESC").fetchall()
    c.close()
    return [dict(r) for r in rows]


def _list_threads() -> list[tuple]:
    rows = list_threads()
    return [(r["id"], r.get("name", ""), r.get("created_at", ""), r.get("updated_at", "")) for r in rows]
