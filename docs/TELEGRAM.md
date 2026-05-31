# Telegram channel

Best Buddy can run as a **Telegram bot** (text chat, long polling). The bot is a **transport** — it calls the same `chat_once` / `run_turn` runtime as the CLI, not a separate LLM tool.

## Setup

1. Open [@BotFather](https://t.me/BotFather) on Telegram → `/newbot` → copy the **bot token**.
2. Get your numeric **user id** (e.g. [@userinfobot](https://t.me/userinfobot) or send `/start` to your bot and check logs).
3. Install the Telegram extra:

```bash
pip install -e '.[telegram,faiss,reliability]'
```

4. Set secrets (preferred over putting tokens in the conf file):

```bash
export TELEGRAM_BOT_TOKEN="your-token"
export TELEGRAM_ALLOWED_USER_ID="123456789"
```

Optional in `conf/best_buddy_agent.conf`:

```ini
[telegram]
enabled = true
```

5. Start the bot from the `best-buddy-agent` directory:

```bash
best-buddy-agent-telegram --config conf/best_buddy_agent.conf
```

## Security (MVP)

Only **one** Telegram user id is allowed (`TELEGRAM_ALLOWED_USER_ID`). All other users are ignored (no reply).

The Telegram entrypoint redacts bot tokens in log output (`httpx` URLs are masked; `httpx`/`httpcore` default to WARNING). Prefer env vars over storing `bot_token` in the conf file. If a token was ever pasted into logs or chat, revoke it in [@BotFather](https://t.me/BotFather) and set `TELEGRAM_BOT_TOKEN` to the new value.

## Threads vs memory

| | CLI | Telegram |
|---|-----|----------|
| Conversation history | `cli-main` | `telegram:dm:<chat_id>` |
| Long-term memory | Shared (`~/.best_buddy_agent/memory.db`) | Same |

Use `/newthread` in Telegram to start a fresh chat history; saved facts remain in the knowledge graph.

## Approvals

Tools `delete_memory` and `write_file` require human approval. The bot sends **Approve** / **Deny** buttons. New messages are blocked until you respond.

## Commands

- `/start` — welcome
- `/help` — short help
- `/newthread` — new conversation thread id

## Troubleshooting

- **Config error: python-telegram-bot** — run `pip install -e '.[telegram]'`.
- **Ollama errors** — the host running the bot must reach `llm_host` in your conf (same as CLI).
- **Trace log** — if `[logging] enabled = true`, use the path printed at startup (`tail -f ...`).

See also [DEBUGGING.md](DEBUGGING.md) and [MEMORY_WORKFLOW.md](MEMORY_WORKFLOW.md).
