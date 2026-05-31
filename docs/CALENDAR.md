# Google Calendar

Best Buddy can read and write Google Calendar events (with approval for writes).

## Setup

1. Use the same Google Cloud project and `credentials.json` as Gmail.
2. Enable **Google Calendar API** in Cloud Console.
3. Save credentials to `~/.best_buddy_agent/gmail/credentials.json`.

```bash
pip install -e '.[calendar]'
best-buddy-agent-calendar-auth --config conf/best_buddy_agent.conf
```

In `conf/best_buddy_agent.conf`:

```ini
[calendar]
enabled = true
```

## Tools

| Tool | Approval |
|------|----------|
| `get_current_datetime` | no |
| `search_events` | no |
| `create_calendar_event` | yes |
| `update_calendar_event` | yes |

Token path: `~/.best_buddy_agent/calendar/token.json` (separate from Gmail token).

## Deadline Watch

When you tap **Approve + Calendar** on a deadline proposal, BB creates a calendar event without a second approval step.
