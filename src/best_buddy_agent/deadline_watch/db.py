"""SQLite persistence for Deadline Watch."""

from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_DATA_DIR = Path(
    os.environ.get("BEST_BUDDY_AGENT_DATA_DIR", Path.home() / ".best_buddy_agent")
)
DB_PATH = _DATA_DIR / "reminders.db"


def _now_iso() -> str:
    return datetime.now().isoformat()


def _conn() -> sqlite3.Connection:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS email_watermarks (
            message_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL DEFAULT '',
            last_seen_at TEXT NOT NULL,
            last_internal_date TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'seen'
        );

        CREATE TABLE IF NOT EXISTS deadline_proposals (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'pending',
            message_id TEXT NOT NULL,
            thread_id TEXT NOT NULL DEFAULT '',
            subject TEXT DEFAULT '',
            sender TEXT DEFAULT '',
            project TEXT DEFAULT '',
            summary TEXT DEFAULT '',
            due_at_utc TEXT NOT NULL,
            confidence REAL DEFAULT 0,
            raw_snippet TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reminder_fires (
            proposal_id TEXT NOT NULL,
            lead_time TEXT NOT NULL,
            fired_at TEXT NOT NULL,
            PRIMARY KEY (proposal_id, lead_time)
        );
        """
    )
    conn.commit()
    return conn


def get_watermark(message_id: str) -> dict | None:
    c = _conn()
    row = c.execute(
        "SELECT * FROM email_watermarks WHERE message_id = ?",
        (message_id,),
    ).fetchone()
    c.close()
    return dict(row) if row else None


def upsert_watermark(
    message_id: str,
    *,
    thread_id: str = "",
    internal_date: str = "",
    status: str = "seen",
) -> None:
    c = _conn()
    c.execute(
        """
        INSERT INTO email_watermarks (message_id, thread_id, last_seen_at, last_internal_date, status)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(message_id) DO UPDATE SET
            thread_id = excluded.thread_id,
            last_seen_at = excluded.last_seen_at,
            last_internal_date = excluded.last_internal_date,
            status = excluded.status
        """,
        (message_id, thread_id, _now_iso(), internal_date, status),
    )
    c.commit()
    c.close()


def should_skip_message(message_id: str, internal_date: str) -> bool:
    wm = get_watermark(message_id)
    if wm is None:
        return False
    if wm.get("status") == "dismissed":
        return True
    if internal_date and wm.get("last_internal_date") == internal_date:
        return wm.get("status") in {"seen", "approved", "dismissed"}
    return False


def create_proposal(
    *,
    message_id: str,
    thread_id: str,
    subject: str,
    sender: str,
    project: str,
    summary: str,
    due_at_utc: str,
    confidence: float,
    raw_snippet: str,
    ttl_hours: int,
) -> str:
    pid = uuid.uuid4().hex[:12]
    now = datetime.now()
    expires = (now + timedelta(hours=max(1, ttl_hours))).isoformat()
    c = _conn()
    c.execute(
        """
        INSERT INTO deadline_proposals
        (id, status, message_id, thread_id, subject, sender, project, summary,
         due_at_utc, confidence, raw_snippet, created_at, expires_at)
        VALUES (?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pid,
            message_id,
            thread_id,
            subject,
            sender,
            project,
            summary,
            due_at_utc,
            confidence,
            raw_snippet,
            now.isoformat(),
            expires,
        ),
    )
    c.commit()
    c.close()
    return pid


def get_proposal(proposal_id: str) -> dict | None:
    c = _conn()
    row = c.execute("SELECT * FROM deadline_proposals WHERE id = ?", (proposal_id,)).fetchone()
    c.close()
    return dict(row) if row else None


def update_proposal_status(proposal_id: str, status: str) -> None:
    c = _conn()
    c.execute(
        "UPDATE deadline_proposals SET status = ? WHERE id = ?",
        (status, proposal_id),
    )
    c.commit()
    c.close()


def has_pending_proposal_for_message(message_id: str) -> bool:
    c = _conn()
    row = c.execute(
        """
        SELECT 1 FROM deadline_proposals
        WHERE message_id = ? AND status = 'pending' AND expires_at > ?
        LIMIT 1
        """,
        (message_id, _now_iso()),
    ).fetchone()
    c.close()
    return row is not None


def record_reminder_fire(proposal_id: str, lead_time: str) -> bool:
    """Record a fired reminder. Returns False if already fired."""
    c = _conn()
    try:
        c.execute(
            "INSERT INTO reminder_fires (proposal_id, lead_time, fired_at) VALUES (?, ?, ?)",
            (proposal_id, lead_time, _now_iso()),
        )
        c.commit()
        c.close()
        return True
    except sqlite3.IntegrityError:
        c.close()
        return False


def expire_stale_proposals() -> int:
    c = _conn()
    cur = c.execute(
        """
        UPDATE deadline_proposals SET status = 'expired'
        WHERE status = 'pending' AND expires_at <= ?
        """,
        (_now_iso(),),
    )
    c.commit()
    count = cur.rowcount
    c.close()
    return count


def list_upcoming_proposals() -> list[dict[str, Any]]:
    c = _conn()
    rows = c.execute(
        """
        SELECT * FROM deadline_proposals
        WHERE status = 'pending' AND expires_at > ?
        ORDER BY created_at DESC
        """,
        (_now_iso(),),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]
