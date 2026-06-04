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


| Service            | Used for                            |
| ------------------ | ----------------------------------- |
| `api.telegram.org` | Telegram bot (required)             |
| DuckDuckGo         | `[web] enabled` → `web_search`      |
| Arbitrary HTTPS    | `fetch_url`, Gmail API (if enabled) |


**Inbound ports:** none (long polling; no webhook).

---

## Directory layout

Everything lives under `/opt/best-buddy-agent/` and is owned by a dedicated `bestbuddy` user:

```text
/opt/best-buddy-agent/
  conf/                 # best_buddy_agent.conf, prompts/
  dist/                 # wheel from dev build (optional after install)
  .venv/                # virtualenv
  data/                 # BEST_BUDDY_AGENT_DATA_DIR (DBs, gmail/*.json)
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

Copy `**conf/**` and `**dist/*.whl**` from your dev machine (see [wheel build](#wheel-build-on-dev-machine) below). No git required on the server.

```bash
sudo mkdir -p /opt/best-buddy-agent/{conf,dist,data,workspace,log,.venv}
sudo chown -R bestbuddy:bestbuddy /opt/best-buddy-agent

# after scp of conf/ and dist/best_buddy_agent-0.1.0-py3-none-any.whl:
sudo -u bestbuddy python3 -m venv /opt/best-buddy-agent/.venv
sudo -u bestbuddy /opt/best-buddy-agent/.venv/bin/pip install -U pip wheel
sudo -u bestbuddy /opt/best-buddy-agent/.venv/bin/pip install \
  '/opt/best-buddy-agent/dist/best_buddy_agent-0.1.0-py3-none-any.whl[telegram,gmail,calendar,faiss,reliability]'
```

Alternative: git clone into `/opt/best-buddy-agent` and `pip install -e '.[telegram,gmail,...]'` (editable dev-style install).

### Wheel build on dev machine

```bash
cd best-buddy-agent
pip install build
python -m build
# artifacts: dist/best_buddy_agent-0.1.0-py3-none-any.whl
tar czf /tmp/best-buddy-conf.tgz conf/
scp dist/*.whl /tmp/best-buddy-conf.tgz user@server:/opt/best-buddy-agent/
```

The wheel installs **Python code only**. You must still deploy `**conf/`** (prompts + `best_buddy_agent.conf`) separately.

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


| Section       | Production values                                                           |
| ------------- | --------------------------------------------------------------------------- |
| `[llm]`       | `llm_host = ubuntu-llm` (or your Ollama host), `llm_model` must exist there |
| `[tools]`     | `files_root = ../workspace`                                                 |
| `[telegram]`  | `enabled = true`                                                            |
| `[web]`       | `enabled = true` if you want internet search                                |
| `[gmail]`     | `enabled = true` after OAuth; paths under `data/` (below)                   |
| `[workflows]` | `enabled = true`                                                            |
| `[logging]`   | `enabled = true`, `file = ../log/trace.log`                                 |


Paths in the config file are relative to `conf/` (e.g. `../data` → install root `data/`).

Gmail paths:

```ini
[gmail]
enabled = true
credentials_path = ../data/gmail/credentials.json
token_path = ../data/gmail/token.json
```

**Secrets** — `/etc/best-buddy/env` (paths relative to install root = systemd `WorkingDirectory`):

```bash
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_USER_ID=123456789
BEST_BUDDY_AGENT_CONF=conf/best_buddy_agent.conf
BEST_BUDDY_AGENT_DATA_DIR=data
```

```bash
sudo mkdir -p /etc/best-buddy
sudo install -m 640 -o root -g bestbuddy /dev/stdin /etc/best-buddy/env <<'EOF'
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_USER_ID=...
BEST_BUDDY_AGENT_CONF=conf/best_buddy_agent.conf
BEST_BUDDY_AGENT_DATA_DIR=data
EOF
```

Use `**640` and group `bestbuddy**` so the service user can read the file when you run `doctor` manually as `bestbuddy`. systemd also reads root-owned `600` files when starting the service, but manual `source /etc/best-buddy/env` as `bestbuddy` needs read permission.

---

## 5. Gmail / Calendar OAuth (one-time)

Gmail needs **two files** under `/opt/best-buddy-agent/data/gmail/`:


| File                 | How you get it                                                                                          |
| -------------------- | ------------------------------------------------------------------------------------------------------- |
| **credentials.json** | Download from [Google Cloud Console](https://console.cloud.google.com/) → OAuth client ID → Desktop app |
| **token.json**       | **Not** downloaded — `best-buddy-agent-gmail-auth` (browser) or `--no-browser` on headless servers      |


See [GMAIL.md](GMAIL.md) for Google Cloud setup and scopes.

### Create token.json (dev machine with browser)

1. Place `credentials.json` at the path in config (or default `data/gmail/`).
2. Run:

```bash
best-buddy-agent-gmail-auth --config conf/best_buddy_agent.conf
```

**Or on a headless server** (no browser — paste code after signing in elsewhere):

```bash
best-buddy-agent-gmail-auth --config /opt/best-buddy-agent/conf/best_buddy_agent.conf --no-browser
```

Open the printed URL on your phone/laptop → after redirect, copy `code=...` from the address bar → paste at the prompt.

1. Confirm:

```bash
best-buddy-agent-gmail-auth --status --config /opt/best-buddy-agent/conf/best_buddy_agent.conf
```

1. If you authenticated on another machine, copy both files to the server:

```bash
sudo mkdir -p /opt/best-buddy-agent/data/gmail
sudo cp credentials.json token.json /opt/best-buddy-agent/data/gmail/
sudo chown -R bestbuddy:bestbuddy /opt/best-buddy-agent/data
```

Or rsync the whole data dir from dev (§6), which includes `gmail/` if you already authenticated locally.

Calendar (optional): `best-buddy-agent-calendar-auth` — separate `calendar/token.json`; can reuse the same `credentials.json`.

Restart the Telegram service after adding or replacing tokens.

---

## 6. Migrate data from dev machine (optional)

```bash
rsync -av ~/.best_buddy_agent/ user@server:/opt/best-buddy-agent/data/
ssh user@server 'sudo chown -R bestbuddy:bestbuddy /opt/best-buddy-agent/data'
```

Important files: `memory.db`, `threads.db`, `workflows.db`, `gmail/credentials.json`, `gmail/token.json`, `calendar/` (if used).

If `gmail/token.json` is missing on the server, Gmail tools and deadline watch will fail doctor checks until you complete §5.

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

Create `/etc/systemd/system/best-buddy-telegram.service`.

`ExecStart` must be an **absolute** path to the binary (systemd rejects `.venv/bin/...` even with `WorkingDirectory` set). Repeat the install root in `ReadWritePaths` / `ReadOnlyPaths` — systemd does not prefix those from `WorkingDirectory`.

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
ExecStart=/opt/best-buddy-agent/.venv/bin/best-buddy-agent-telegram --config /opt/best-buddy-agent/conf/best_buddy_agent.conf
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


| Task           | Command                                                                                                                                              |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| Logs (systemd) | `journalctl -u best-buddy-telegram -f`                                                                                                               |
| Trace log      | `tail -f /opt/best-buddy-agent/log/trace.log`                                                                                                        |
| Restart        | `sudo systemctl restart best-buddy-telegram`                                                                                                         |
| Health check   | `sudo -u bestbuddy bash -c 'set -a; source /etc/best-buddy/env; set +a; /opt/best-buddy-agent/.venv/bin/best-buddy-agent-doctor --profile telegram'` |
| Update code    | See below                                                                                                                                            |


**Update workflow:**

```bash
# on dev: rebuild wheel, scp conf if prompts changed
cd best-buddy-agent && python -m build
scp dist/best_buddy_agent-0.1.0-py3-none-any.whl user@server:/opt/best-buddy-agent/dist/

# on server
sudo -u bestbuddy /opt/best-buddy-agent/.venv/bin/pip install \
  '/opt/best-buddy-agent/dist/best_buddy_agent-0.1.0-py3-none-any.whl[telegram,gmail,calendar,faiss,reliability]'
sudo systemctl restart best-buddy-telegram
```

After any `pip install`, restart the service (running process does not load new packages).

---

## 11. Troubleshooting


| Symptom                                      | Likely cause                                                                                          |
| -------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `Temporary failure in name resolution`       | DNS / outbound network on agent host                                                                  |
| `ddgs not installed`                         | Re-run `pip install -e '.[telegram]'` in `/opt/best-buddy-agent/.venv`, restart                       |
| Ollama check fails                           | Wrong `llm_host`, firewall, or model not on LLM server                                                |
| Bot silent                                   | Wrong `TELEGRAM_ALLOWED_USER_ID`                                                                      |
| Gmail tools missing                          | `credentials.json` + `token.json` under `data/gmail/` — see §5 and [GMAIL.md](GMAIL.md)               |
| `Permission denied` on `/etc/best-buddy/env` | Use `chmod 640` and `chgrp bestbuddy` (§4) for manual doctor as `bestbuddy`                           |
| `Read-only file system` on trace.log         | `ReadWritePaths` must include `%h/log`; `bestbuddy` home (`useradd -d`) must match `WorkingDirectory` |
| systemd start fails after hardening          | `getent passwd bestbuddy` home must equal `WorkingDirectory`; see `journalctl -u best-buddy-telegram` |
| Permission denied on log/data                | `chown -R bestbuddy:bestbuddy /opt/best-buddy-agent`                                                  |
| Doctor STT `CUDA … out of memory` on 2nd instance | GPU already holds Ollama + first bot’s `large-v3`; doctor loads Whisper again. `large-v3` **is** cached under `/opt/huggingface/cache`. Set `stt.device = cpu` (or `enabled = false`) on the second instance’s conf. Run doctor with `source /etc/best-buddy/env_andrey`. |


---

## 12. What not to run in production

- **CLI** (`best-buddy-agent-chat`) — local debugging only.
- **Two bots with the same token** — stop the dev machine bot before starting the server.

---

See also: [TELEGRAM.md](TELEGRAM.md), [GMAIL.md](GMAIL.md), [DEBUGGING.md](DEBUGGING.md).