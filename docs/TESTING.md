# Testing

## Run (CI default)

```bash
.venv/bin/pytest tests -q
```

No network; uses pydantic-ai `TestModel` at the `agent_runtime` boundary. Do **not** monkeypatch `pydantic_ai.*` internals.

## Layers

1. **Unit** — `TestModel(call_tools=[])` for text-only turns; tool router tests for filesystem/memory.
2. **Trace** — `test_agent_trace.py` parses `agent_trace.read_trace_blocks()`.
3. **Workflow** — scheduler, pause/resume, NL plan creation (mocked `Agent.run_sync`).
4. **Live Ollama** (optional):

```bash
BEST_BUDDY_AGENT_OLLAMA_TEST=1 .venv/bin/pytest tests -m ollama -q
```

## Fixtures (`tests/conftest.py`)

- `agent_config` — minimal valid config
- `trace_config` — config + temp trace log path

## Install for development

```bash
pip install -e 'best_buddy_agent[dev,reliability]'
```
