# Best Buddy agent — foundation remediation

## Phase 2 complete (single paths)

| Area | Canonical path | Removed |
|------|----------------|---------|
| LLM | `llm_runner.run_text_completion()` + `model_factory.build_ollama_model()` | `models.ollama_generate` (`/api/generate`) |
| Tools | `@agent.tool` in `agent_runtime` | `tool_router.execute_tool` |
| Thread history | `thread_message_batches` + `load_thread_message_history()` | `messages` role/content writes |
| Observability | `agent_trace` + `trace_logging` (local file) | Logfire / cloud UI |
| Memory recall | `memory_recall.recall_memories()` | Duplicate logic in `memory_tools` / `agent_context` |

## Config

```ini
[logging]
enabled = true
file = agent-trace.log

[agent]
reliability_required = false
```

## Still open

- Workflow HITL → string instead of `InterruptResult`
- Dual HITL (workflow approval steps vs agent deferred tools)
- `best_buddy_agent_1/` duplicate package in repo
- legacy `companion_api` (pre-rename) separate `_ollama_generate`
- `timeout_sec` not wired
