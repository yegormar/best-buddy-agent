# Gmail (read + drafts)

Best Buddy can search and read your Gmail and **create drafts**. There is **no send-email tool** (ported from Thoth with send disabled by default; BB omits send entirely).

## Setup

1. [Google Cloud Console](https://console.cloud.google.com/): create a project, enable **Gmail API**.
2. OAuth consent screen (External → add your Gmail as test user if in testing mode).
3. Credentials → **OAuth client ID** → Desktop app → download JSON.
4. Save as `~/.best_buddy_agent/gmail/credentials.json` (or path in config).

```bash
pip install -e '.[gmail]'
```

In `conf/best_buddy_agent.conf`:

```ini
[gmail]
enabled = true
# credentials_path = ../.data/gmail/credentials.json
# token_path = ../.data/gmail/token.json
```

Authenticate (opens browser):

```bash
best-buddy-agent-gmail-auth --config conf/best_buddy_agent.conf
best-buddy-agent-gmail-auth --status --config conf/best_buddy_agent.conf
```

Restart CLI or Telegram bot. When `enabled = true` and token exists, BB gets:

| Tool | Role |
|------|------|
| `search_gmail` | Inbox search (Gmail `q` syntax) |
| `get_gmail_message` | Full message by id |
| `get_gmail_thread` | Full thread by id |
| `create_gmail_draft` | Draft only (requires approval on CLI/Telegram) |

## OAuth scopes

- `gmail.readonly` — read mail  
- `gmail.compose` — create drafts (Google's scope name; BB does not call `messages.send`)

## Thoth compatibility

Uses the same layout as Thoth: `~/.best_buddy_agent/gmail/credentials.json` and `token.json`. Thoth's `token.json` (full `mail.google.com` scope) is not interchangeable — re-run `best-buddy-agent-gmail-auth` once.

## Security

- Do not commit `credentials.json` or `token.json`.
- `create_gmail_draft` uses human approval (like `write_file`).
