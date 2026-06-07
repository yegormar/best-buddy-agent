# best-buddy-agent

Standalone Python agent for memory, context, workflows, and proactive reminders —
configured for **locally hosted Ollama** and **pydantic-ai** (no LangChain).

## Included

- **Agent runtime** (`agent_runtime.py`, `approval.py`, `agent_trace.py`) — pydantic-ai + Ollama + local trace file
- Knowledge graph memory core (`knowledge_graph.py`)
- Background memory extraction (`memory_extraction.py`) and dream cycle (`dream_cycle.py`)
- Orchestrator delegate (`orchestrator.py`) → `run_turn()`
- **Tools** (`tools/`) — filesystem, memory, workflows, Gmail, Calendar, web, vision
- **Workflow engine** (`workflow_engine.py`) — typed steps, scheduler, `create_reminder`
- **Deadline Watch** (`deadline_watch/`) — Gmail scan → Telegram approval → reminders (see [docs/DEADLINE_WATCH.md](docs/DEADLINE_WATCH.md))
- Lightweight thread store (`threads.py`)
- Interactive chat CLI (`runtime.py`, `cli.py`)
- **Telegram channel** (`channels/telegram.py`) — text, voice (STT), photos (vision), Markdown→HTML formatting
- Optional integrations: Gmail ([docs/GMAIL.md](docs/GMAIL.md)), Calendar ([docs/CALENDAR.md](docs/CALENDAR.md))

## Configuration

Copy and edit `conf/best_buddy_agent.conf.example` → `conf/best_buddy_agent.conf`.

| Section | Purpose |
|---------|---------|
| `[llm]` | Ollama host, model, sampling, `llm_num_ctx`, `llm_think` (non-thinking mode when `false`) |
| `[prompts]` | `language` — prompt bundle under `conf/prompts/{language}/` |
| `[tools]` | `files_root`, `max_tool_iterations` |
| `[web]` | DuckDuckGo search + URL fetch (`web_search`, `fetch_url`) |
| `[logging]` | Local trace file — see [docs/DEBUGGING.md](docs/DEBUGGING.md) |
| `[agent]` | `assistant_name`, `reliability_required` |
| `[telegram]` | Bot channel; secrets via env vars (see [docs/TELEGRAM.md](docs/TELEGRAM.md)) |
| `[stt]` | Voice notes → faster-whisper (Telegram only) |
| `[vision]` | Photo → native multimodal + `revisit_image` follow-ups |
| `[gmail]` | Read + drafts — [docs/GMAIL.md](docs/GMAIL.md) |
| `[calendar]` | Google Calendar — [docs/CALENDAR.md](docs/CALENDAR.md) |
| `[workflows]` | Background scheduler (`enabled`, `poll_seconds`) |
| `[deadline_watch]` | Proactive Gmail deadline scan — [docs/DEADLINE_WATCH.md](docs/DEADLINE_WATCH.md) |

Optional `agent_system_prompt_file` in `[llm]` overrides only `agent_system.txt` for the chosen locale.

Config path: env `BEST_BUDDY_AGENT_CONF` or CLI `--config`.

**Memory:** [docs/MEMORY_WORKFLOW.md](docs/MEMORY_WORKFLOW.md) (developers) · [docs/MEMORY_WORKFLOW_AI.md](docs/MEMORY_WORKFLOW_AI.md) (AI assistants).

**Architecture & debugging:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/DEBUGGING.md](docs/DEBUGGING.md) · [docs/MIGRATION_PYDANTIC_AI.md](docs/MIGRATION_PYDANTIC_AI.md)

## Data directory

By default state is stored in `~/.best_buddy_agent`. Override with `BEST_BUDDY_AGENT_DATA_DIR`.

Typical files: `memory.db`, `threads.db`, `workflows.db`, `reminders.db`, `memory_vectors/`, `vision_cache/`, `gmail/`, `calendar/`.

## Install

```bash
pip install -e '.[dev,reliability,faiss]'
```

Optional extras:

| Extra | Enables |
|-------|---------|
| `telegram` | `best-buddy-agent-telegram` |
| `stt` | Voice transcription (faster-whisper) |
| `gmail` | Gmail read + drafts |
| `calendar` | Google Calendar |
| `faiss` | Semantic memory recall index |
| `reliability` | Summarization + stuck-loop detection |

Production Telegram bot: `pip install -e '.[telegram,stt,gmail,calendar,faiss,reliability]'`

## Run tests

```bash
.venv/bin/pytest tests -q
```

Optional live Ollama: `BEST_BUDDY_AGENT_OLLAMA_TEST=1 pytest tests -m ollama -q`

## Startup checks

`best-buddy-agent-doctor` validates config, data paths, SQLite DBs, Ollama + model,
optional Gmail/Calendar, deadline watch prerequisites, FAISS index, reliability packages,
and (with `--profile telegram`) Telegram, STT self-test, and Ollama vision capability.

```bash
best-buddy-agent-doctor --config conf/best_buddy_agent.conf
best-buddy-agent-doctor --config conf/best_buddy_agent.conf --profile telegram
```

Profiles: `chat`, `telegram`, or `all`.

## Run interactive agent

```bash
.venv/bin/python -m best_buddy_agent.cli --config conf/best_buddy_agent.conf
```

or after editable install:

```bash
best-buddy-agent-chat --config conf/best_buddy_agent.conf
```

## Run Telegram bot

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_USER_ID` (see [docs/TELEGRAM.md](docs/TELEGRAM.md)), then:

```bash
best-buddy-agent-telegram --config conf/best_buddy_agent.conf
```

**Dedicated server:** see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## CLI entry points

| Command | Purpose |
|---------|---------|
| `best-buddy-agent-chat` | Interactive CLI |
| `best-buddy-agent-telegram` | Telegram bot (workflows + deadline watch scheduler) |
| `best-buddy-agent-doctor` | Startup validation |
| `best-buddy-agent-gmail-auth` | Gmail OAuth |
| `best-buddy-agent-calendar-auth` | Calendar OAuth |
| `best-buddy-agent-system-test` | Live smoke tests — [docs/SYSTEM_TESTS.md](docs/SYSTEM_TESTS.md) |

## Notes

- `wiki_vault` is wired as a no-op in standalone mode.
- Human approval required for: `write_file`, `delete_memory`, `create_gmail_draft`, `create_calendar_event`, `update_calendar_event` (CLI prompt or Telegram buttons).
