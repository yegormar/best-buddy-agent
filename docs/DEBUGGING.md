# Debugging best_buddy_agent (local trace file)

Observability is a **local trace file** with copy-paste friendly blocks (`===== TITLE =====`). No cloud token required.

## Enable tracing

In `best_buddy_agent.conf`:

```ini
[logging]
enabled = true
file = agent-trace.log
log_prompts = true
log_responses = true
log_message_history = true
log_tool_args = true
# Exact HTTP JSON sent to Ollama /v1/chat/completions and the raw response body:
log_llm_wire = true
```

`file` may be relative to the config directory. The parent directory must exist.

### Exact LLM HTTP payload (`log_llm_wire`)

Set `log_llm_wire = true` (requires `enabled = true` and `file`). Each model HTTP round-trip appends:

| Block | Contents |
|-------|----------|
| `LLM WIRE REQUEST` | Method, URL, pretty-printed JSON body posted to `/v1/chat/completions` |
| `LLM WIRE RESPONSE` | Status, URL, pretty-printed JSON body returned by Ollama |

This is the **actual wire format** (system message, tools, messages, `num_ctx`, etc.), not the reconstructed `ROUTING SNAPSHOT`.

## Run chat

```bash
.venv/bin/python -m best_buddy_agent.cli --config conf/best_buddy_agent.conf
```

On CLI startup, the resolved trace path is printed (`Trace log (tail -f): ...`). Use that path with `tail -f` (not `BEST_BUDDY_AGENT_DATA_DIR`).

After a turn, open that file. New blocks appear at **turn start** (before the model finishes). Typical blocks:

| Block | Contents |
|-------|----------|
| `CHAT TURN START` / `END` | CLI wrapper timing and reply preview |
| `ROUTING SNAPSHOT` | Recall meta, instructions, prior thread lines, tool catalog |
| `TURN START` / `END` | Agent run timing and message counts |
| `INSTRUCTIONS` | Full system prompt (or redacted if `log_prompts=false`) |
| `MESSAGE HISTORY` | Prior pydantic-ai messages for the thread |
| `MODEL REQUEST` / `MODEL RESPONSE` | Per-step model I/O |
| `TOOL CALL` / `TOOL RESULT` | Tool invocations and outcomes |
| `LLM WIRE REQUEST` / `RESPONSE` | Exact HTTP JSON to/from Ollama (`log_llm_wire=true`) |
| `DEFERRED TOOL PENDING` / `DEFERRED RESUME` | Human-in-the-loop approval flow |

Paste one or more blocks into bug reports or to a coding assistant.

## Human-in-the-loop

Destructive tools (`write_file`, `delete_memory`) use pydantic-ai `requires_approval`. The CLI prompts `Approve? [y/N]`.

## Memory recall

See [MEMORY_WORKFLOW.md](MEMORY_WORKFLOW.md) (developer) and [MEMORY_WORKFLOW_AI.md](MEMORY_WORKFLOW_AI.md) (agents) for the full read/write/extract/dream picture.

All recall (instruction injection and `search_memory` tool) goes through `memory_recall.recall_memories()`.

Pipeline (see `ARCHITECTURE.md`): `semantic` → `keyword` → `list_recent` when FAISS/SQL miss.

`ROUTING SNAPSHOT` shows `recall_path` and `injected_subjects`. If you see `list_recent` on a
Russian query, that is expected with `LocalHashEmbedding` — not a missing regex list.

If the model answers identity questions without calling tools, check whether the injected
"You KNOW the following facts…" block already contains the name (auto-recall), per
`conf/prompts/{language}/agent_system.txt` and `conf/prompts/{language}/fragments/memory_recall_header.txt`.

## Tests

Tests use `[logging] enabled = false` in fixtures so pytest does not write trace files.
