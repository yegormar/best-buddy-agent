# Gmail (read + drafts)

Best Buddy can search and read your Gmail and **create drafts**. There is **no send-email tool** (ported from Thoth with send disabled by default; BB omits send entirely).

## Setup

1. [Google Cloud Console](https://console.cloud.google.com/): create a project, enable **Gmail API**.
2. OAuth consent screen (External → add your Gmail as test user if in testing mode).
3. Credentials → **OAuth client ID** → Desktop app → download JSON.
4. Save as `~/.best_buddy_agent/gmail/credentials.json` (or `credentials_path` in config).

```bash
pip install -e '.[gmail]'
```

In `conf/best_buddy_agent.conf`:

```ini
[gmail]
enabled = true
# credentials_path = /opt/best-buddy-agent/data/gmail/credentials.json
# token_path = /opt/best-buddy-agent/data/gmail/token.json
```

## credentials.json vs token.json

| File | Source | What it is |
|------|--------|------------|
| **credentials.json** | Download from Google Cloud (OAuth Desktop client) | App identity — not tied to your inbox yet |
| **token.json** | Created by `best-buddy-agent-gmail-auth` | Your granted access (refresh token); written after you sign in in the browser |

You do **not** download `token.json` from Google Cloud. Only `credentials.json` comes from the console.

### Create token.json (one-time OAuth)

**Option A — machine with a browser (easiest):**

```bash
best-buddy-agent-gmail-auth --config conf/best_buddy_agent.conf
```

**Option B — headless server (no browser):**

```bash
best-buddy-agent-gmail-auth --config conf/best_buddy_agent.conf --no-browser
```

1. The CLI prints a Google sign-in URL.
2. Open that URL on your phone or laptop and sign in.
3. After redirect, the browser page may show “can’t connect” — normal for Desktop OAuth.
4. Copy the `code=...` value from the address bar (or paste the full redirect URL).
5. Paste into the terminal; `token.json` is written.

Then verify:

```bash
best-buddy-agent-gmail-auth --status --config conf/best_buddy_agent.conf
```

Expect `Token is valid` (or similar).

### Deploy tokens to a server

If you authenticated on your dev machine, copy both files to the server:

```bash
scp credentials.json token.json user@server:/opt/best-buddy-agent/data/gmail/
ssh user@server 'chown -R bestbuddy:bestbuddy /opt/best-buddy-agent/data/gmail'
```

Paths must match `[gmail] credentials_path` and `token_path` in the server config.

### When to re-run auth

- Token revoked or expired and refresh fails
- You replaced `credentials.json` (new OAuth client)
- Migrating from Thoth’s token (different scopes) — run `best-buddy-agent-gmail-auth` once for Best Buddy
- **`Missing required parameter: redirect_uri`** — use a **Desktop app** OAuth client (not Web), re-download `credentials.json`, and use a build with `--no-browser` that sets `redirect_uri` (or auth on a machine with a browser)

### Google Cloud checklist

- OAuth client type: **Desktop app** (not “Web application”)
- `credentials.json` should contain `"installed": { ..., "redirect_uris": ["http://localhost", ...] }`
- Test users: add your Gmail on the OAuth consent screen if the app is in **Testing** mode

Restart CLI or Telegram bot after updating tokens.

## Tools (after auth)

When `enabled = true` and both files exist, BB loads:

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
