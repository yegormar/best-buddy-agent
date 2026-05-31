# pydantic-ai migration (best_buddy_agent)

## Status

`best_buddy_agent` uses **pydantic-ai** for the agent loop (Ollama via OpenAI-compatible API). LangChain/LangGraph are **not** dependencies.

## Verify zero LangChain

```bash
bash scripts/verify_no_langchain.sh
pip freeze | rg -i 'langchain|langgraph'  # should be empty
```

## Architecture

- **Runtime:** [`agent_runtime.py`](../src/best_buddy_agent/agent_runtime.py) — `build_agent()`, `run_turn()`, `resume_turn()`
- **Observability:** [`agent_trace.py`](../src/best_buddy_agent/agent_trace.py) + [`trace_logging.py`](../src/best_buddy_agent/trace_logging.py) — local trace file (`[logging]`)
- **Memory recall:** [`memory_recall.py`](../src/best_buddy_agent/memory_recall.py)
- **Foundation remediation:** [`FOUNDATION_REMEDIATION.md`](FOUNDATION_REMEDIATION.md)
- **Tools:** [`tools/`](../src/best_buddy_agent/tools/) — filesystem, memory, workflow status
- **Memory:** unchanged SQLite + NetworkX + FAISS ([`knowledge_graph.py`](../src/best_buddy_agent/knowledge_graph.py))
- **Workflows:** [`workflow_engine.py`](../src/best_buddy_agent/workflow_engine.py) — prompt steps call `run_turn()`; NL plans use `WorkflowPlan` structured output

## Optional reliability extras

```bash
pip install -e 'best_buddy_agent[reliability]'
```

Enables pydantic-deep capabilities: summarization, orphan tool-call repair, stuck-loop detection (when packages import cleanly).

## Thoth cutover gate (do not merge Thoth until all pass)

- [ ] `rg langchain|langgraph best_buddy_agent` clean in `src/` and `tests/`
- [ ] `pytest tests -q` (no Ollama)
- [ ] CLI multi-turn with Logfire enabled
- [ ] Workflow: prompt → approval → prompt with persisted run state
- [ ] HITL: deferred tool approve/deny in CLI
- [ ] Memory/dream/extraction tests unchanged

## MemPalace

Evaluated and **declined** for this milestone — best-buddy-agent keeps entity–relation memory, not verbatim palace indexing.
