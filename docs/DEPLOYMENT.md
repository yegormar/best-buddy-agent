# Deployment (dedicated server)

Production setup: **one long-running Telegram bot process** on a server. It handles chat, workflows, deadline watch, and notifications. The LLM can run on the same host or a separate GPU machine (Ollama).

**Install root:** `/opt/best-buddy-agent/`

## Architecture

```text
Telegram users
      │
      ▼
┌─────────────────────────────────────┐
│  Dedicated server (agent host)      │
│  best-buddy-agent-telegram          │
│    ├─ Telegram long polling         │
│    ├─ workflow scheduler            │
│    └─ deadline watch (if enabled)   │
└──────────┬──────────────────────────┘
           │ HTTP :11434 (or your port)
           ▼
┌─────────────────────────────────────┐
│  LLM host (optional separate box)   │
│  Ollama — llm_host in config         │
└─────────────────────────────────────┘
```

**Outbound internet required on the agent host:**

| Service | Used for |
|---------|----------|
| `api.telegram.org` | Telegram bot (required) |
| DuckDuckGo | `[web] enabled` → `web_search` |
| Arbitrary HTTPS | `fetch_url`, Gmail API (if enabled) |

**Inbound ports:** none (long polling; no webhook).

---

## Directory layout

Everything lives under `/opt/best-buddy-agent/` and is owned by a dedicated `bestbuddy` user:

```text
/opt/best-buddy-agent/
  conf/                 # best_buddy_agent.conf, prompts/
  src/                  # Python package
  .venv/                # virtualenv
  data/                 # BEST_BUDDY_AGENT_DATA_DIR (DBs, Gmail tokens)
  workspace/            # files_root — only path file tools may use
  log/                  # trace log
```

Agent file tools (`read_file`, `write_file`) cannot access paths outside `workspace/` (enforced in code). systemd further blocks the rest of the filesystem (see §8).

---

## 1. Server prerequisites

- Ubuntu (or Linux with systemd)
- Python **3.11+** (3.12/3.13 recommended for production)
- Git
- Stable DNS and outbound HTTPS

Optional separate LLM server:

- Ollama listening on a reachable hostname (e.g. `ubuntu-llm:11434`)
- Model pulled: `ollama pull <llm_model from config>`

---

## 2. Create user and directories

```bash
sudo useradd -r -d /opt/best-buddy-agent -s /usr/sbin/nologin bestbuddy
sudo mkdir -p /opt/best-buddy-agent/{data,workspace,log}
sudo chown -R bestbuddy:bestbuddy /opt/best-buddy-agent
```

---

## 3. Install application

As root or your deploy user, then hand ownership to `bestbuddy`:

```bash
sudo mkdir -p /opt/best-buddy-agent
cd /opt/best-buddy-agent

# Clone (or rsync from dev machine)
sudo git clone <your-repo-url> .
# If the repo root is best-buddy/best-buddy-agent/, copy that tree here instead.

sudo -u bestbuddy python3 -m venv /opt/best-buddy-agent/.venv
sudo -u bestbuddy /opt/best-buddy-agent/.venv/bin/pip install -U pip wheel
sudo -u bestbuddy /opt/best-buddy-agent/.venv/bin/pip install -e '.[telegram,gmail,calendar,faiss,reliability]'
```

Verify web tools (if `[web] enabled = true`):

```bash
/opt/best-buddy-agent/.venv/bin/python -c "from ddgs import DDGS; import httpx; print('ok')"
```

Ensure `bestbuddy` owns the tree:

```bash
sudo chown -R bestbuddy:bestbuddy /opt/best-buddy-agent
```

---

## 4. Configuration

```bash
sudo -u bestbuddy cp /opt/best-buddy-agent/conf/best_buddy_agent.conf.example \
  /opt/best-buddy-agent/conf/best_buddy_agent.conf
```

Edit `/opt/best-buddy-agent/conf/best_buddy_agent.conf`:

| Section | Production values |
|---------|-------------------|
| `[llm]` | `llm_host = ubuntu-llm` (or your Ollama host), `llm_model` must exist there |
| `[tools]` | `files_root = /opt/best-buddy-agent/workspace` |
| `[telegram]` | `enabled = true` |
| `[web]` | `enabled = true` if you want internet search |
| `[gmail]` | `enabled = true` after OAuth; set paths under `data/` (below) |
| `[workflows]` | `enabled = true` |
| `[logging]` | `enabled = true`, `file = /opt/best-buddy-agent/log/trace.log` |

Gmail paths (explicit, under data dir):

```ini
[gmail]
enabled = true
credentials_path = /opt/best-buddy-agent/data/gmail/credentials.json
token_path = /opt/best-buddy-agent/data/gmail/token.json
```

**Secrets** — `/etc/best-buddy/env` (mode `600`, root-owned):

```bash
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_USER_ID=123456789
BEST_BUDDY_AGENT_CONF=/opt/best-buddy-agent/conf/best_buddy_agent.conf
BEST_BUDDY_AGENT_DATA_DIR=/opt/best-buddy-agent/data
```

```bash
sudo mkdir -p /etc/best-buddy
sudo install -m 600 /dev/stdin /etc/best-buddy/env <<'EOF'
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_USER_ID=...
BEST_BUDDY_AGENT_CONF=/opt/best-buddy-agent/conf/best_buddy_agent.conf
BEST_BUDDY_AGENT_DATA_DIR=/opt/best-buddy-agent/data
EOF
```

---

## 5. Gmail / Calendar OAuth (one-time)

On a machine with a browser, then copy to the server:

```bash
best-buddy-agent-gmail-auth --config /path/to/best_buddy_agent.conf
```

Copy to server:

```bash
sudo mkdir -p /opt/best-buddy-agent/data/gmail
sudo cp credentials.json token.json /opt/best-buddy-agent/data/gmail/
sudo chown -R bestbuddy:bestbuddy /opt/best-buddy-agent/data
```

See [GMAIL.md](GMAIL.md).

---

## 6. Migrate data from dev machine (optional)

```bash
rsync -av ~/.best_buddy_agent/ user@server:/opt/best-buddy-agent/data/
ssh user@server 'sudo chown -R bestbuddy:bestbuddy /opt/best-buddy-agent/data'
```

Important files: `memory.db`, `threads.db`, `workflows.db`, `gmail/`, `calendar/`.

---

## 7. Preflight

```bash
sudo -u bestbuddy bash -c '
  set -a; source /etc/best-buddy/env; set +a
  /opt/best-buddy-agent/.venv/bin/best-buddy-agent-doctor \
    --config /opt/best-buddy-agent/conf/best_buddy_agent.conf \
    --profile telegram
'
```

All checks should pass before enabling systemd.

---

## 8. Smoke test (manual)

```bash
sudo -u bestbuddy bash -c '
  set -a; source /etc/best-buddy/env; set +a
  cd /opt/best-buddy-agent
  .venv/bin/best-buddy-agent-telegram --config conf/best_buddy_agent.conf
'
```

Send a Telegram message, then Ctrl+C.

---

## 9. systemd service (isolated user)

Create `/etc/systemd/system/best-buddy-telegram.service`:

```ini
[Unit]
Description=Best Buddy Telegram agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=bestbuddy
Group=bestbuddy
WorkingDirectory=/opt/best-buddy-agent
EnvironmentFile=/etc/best-buddy/env
ExecStart=/opt/best-buddy-agent/.venv/bin/best-buddy-agent-telegram \
  --config /opt/best-buddy-agent/conf/best_buddy_agent.conf
Restart=on-failure
RestartSec=10

# Filesystem isolation — process cannot write outside these paths
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
NoNewPrivileges=true
ReadWritePaths=/opt/best-buddy-agent/data /opt/best-buddy-agent/workspace /opt/best-buddy-agent/log
ReadOnlyPaths=/opt/best-buddy-agent/conf /opt/best-buddy-agent/src /opt/best-buddy-agent/.venv

# Outbound network (Telegram, web search, Gmail, remote Ollama)
RestrictAddressFamilies=AF_INET AF_INET6

[Install]
WantedBy=multi-user.target
```

Enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now best-buddy-telegram
sudo systemctl status best-buddy-telegram
sudo journalctl -u best-buddy-telegram -f
```

---

## 10. Operations

| Task | Command |
|------|---------|
| Logs (systemd) | `journalctl -u best-buddy-telegram -f` |
| Trace log | `tail -f /opt/best-buddy-agent/log/trace.log` |
| Restart | `sudo systemctl restart best-buddy-telegram` |
| Health check | `sudo -u bestbuddy bash -c 'set -a; source /etc/best-buddy/env; set +a; /opt/best-buddy-agent/.venv/bin/best-buddy-agent-doctor --profile telegram'` |
| Update code | See below |

**Update workflow:**

```bash
cd /opt/best-buddy-agent
sudo git pull
sudo -u bestbuddy .venv/bin/pip install -e '.[telegram,gmail,calendar,faiss,reliability]'
sudo systemctl restart best-buddy-telegram
```

After any `pip install`, restart the service (running process does not load new packages).

---

## 11. Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| `Temporary failure in name resolution` | DNS / outbound network on agent host |
| `ddgs not installed` | Re-run `pip install -e '.[telegram]'` in `/opt/best-buddy-agent/.venv`, restart |
| Ollama check fails | Wrong `llm_host`, firewall, or model not on LLM server |
| Bot silent | Wrong `TELEGRAM_ALLOWED_USER_ID` |
| Gmail tools missing | Token missing under `/opt/best-buddy-agent/data/gmail/` |
| systemd start fails after hardening | Add missing path to `ReadWritePaths`; check `journalctl -u best-buddy-telegram` |
| Permission denied on log/data | `chown -R bestbuddy:bestbuddy /opt/best-buddy-agent` |

---

## 12. What not to run in production

- **CLI** (`best-buddy-agent-chat`) — local debugging only.
- **Two bots with the same token** — stop the dev machine bot before starting the server.

---

See also: [TELEGRAM.md](TELEGRAM.md), [GMAIL.md](GMAIL.md), [DEBUGGING.md](DEBUGGING.md).
