# System smoke tests

Live end-to-end checks against your **real** Best Buddy setup (memory, Gmail, workflows). These are not unit tests — they call Ollama and your `~/.best_buddy_agent` data.

## Setup (once)

1. Copy and edit expectations:

```bash
cp tests/system/expectations.example.json tests/system/expectations.json
```

Set `memory.expected_age`, `memory.must_contain`, and adjust Gmail/scheduling prompts if needed.

2. Ensure services are ready:

```bash
best-buddy-agent-doctor --config conf/best_buddy_agent.conf
```

Gmail OAuth, Ollama reachable, `[gmail]` and `[workflows]` enabled.

## Run

```bash
best-buddy-agent-system-test --config conf/best_buddy_agent.conf
```

Or manually:

```bash
export BEST_BUDDY_AGENT_SYSTEM_TEST=1
export BEST_BUDDY_AGENT_OLLAMA_TEST=1
export BEST_BUDDY_AGENT_CONF=conf/best_buddy_agent.conf
pytest tests/system -v
```

Scheduler-only (no LLM):

```bash
best-buddy-agent-system-test --no-ollama -k scheduling_engine
```

## What each test does

| Test | Needs LLM | Needs Gmail | What it verifies |
|------|-----------|-------------|------------------|
| `test_memory_age` | yes | no | Asks your age; matches `expected_age` |
| `test_memory_known_facts` | yes | no | Lists facts; checks `must_contain` strings |
| `test_gmail_create_draft` | no | yes | Creates draft via Gmail API directly; cleanup after |
| `test_scheduling_agent_create_reminder` | yes | no | Agent calls `create_reminder`; row in `workflows.db` |
| `test_scheduling_engine_fires_notifier` | no | no | Scheduler fires mock notifier (no Telegram) |

## Telegram

These tests **do not** drive the Telegram bot. Chat uses the same `chat_once` path as CLI/Telegram. Reminder delivery to your phone requires the bot running — use the engine test for scheduler logic, or test manually.

## Gmail test safety

The Gmail smoke test calls `create_gmail_draft` **directly** (not via the LLM agent). An earlier version asked the agent to create a draft with auto-approve; `create_gmail_draft` requires HITL, and the agent + auto-approve loop could run for many minutes and spam the trace log. It does **not** create thousands of real drafts — the scary log count is the same tool result repeated in message history on every turn.

## Environment variables

| Variable | Purpose |
|----------|---------|
| `BEST_BUDDY_AGENT_SYSTEM_TEST=1` | Enable system tests; use real data dir |
| `BEST_BUDDY_AGENT_OLLAMA_TEST=1` | Enable LLM-backed tests |
| `BEST_BUDDY_AGENT_CONF` | Path to config file |
| `BEST_BUDDY_AGENT_SYSTEM_TEST_TIMEOUT` | Per-turn timeout seconds (default 180) |
