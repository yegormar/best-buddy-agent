# Deadline Watch

Proactive Gmail scanning that detects project deadlines and asks for your approval before scheduling Telegram reminders (and optional Google Calendar events).

## Requirements

- Gmail configured (`[gmail] enabled = true`, OAuth done)
- Telegram bot running (`best-buddy-agent-telegram`) — reminders are Telegram-only
- Optional: Calendar for **Approve + Calendar** button

## Config

```ini
[workflows]
enabled = true
poll_seconds = 30

[deadline_watch]
enabled = true
scan_interval_seconds = 900
gmail_query = is:unread newer_than:7d
timezone = Europe/Berlin
lead_times = 1d,0d,1h
proposal_ttl_hours = 72
```

## Flow

1. **Scan** — every `scan_interval_seconds`, workflow `deadline-watch-scan` reads new Gmail matching `gmail_query`.
2. **Extract** — LLM extracts structured deadlines (project, due date, confidence).
3. **Propose** — Telegram message with **Approve reminders**, **Approve + Calendar**, or **Dismiss**.
4. **On approve** — saves `event` memory with `properties.due_at`, schedules one-shot `notify_only` workflows per `lead_time`, optionally creates a calendar event.
5. **Remind** — at each lead time, BB sends a Telegram message.

## Dedupe

- Processed emails tracked in `{BEST_BUDDY_AGENT_DATA_DIR}/reminders.db` (default `~/.best_buddy_agent/reminders.db`)
- Dismissed emails are not re-proposed unless the thread updates
- Reminder fires recorded per `(proposal_id, lead_time)`

## Troubleshooting

- No proposals: check Gmail query, unread mail, and that messages contain concrete dates
- No reminders: Telegram bot must stay running (scheduler starts with the bot)
- Run `best-buddy-agent-doctor --config conf/best_buddy_agent.conf` for startup checks
