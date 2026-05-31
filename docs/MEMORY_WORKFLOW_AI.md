# Memory workflow (AI assistant reference)

**Audience:** Cursor / coding agents editing `best-buddy-agent`.
**Human-readable guide:** [MEMORY_WORKFLOW.md](MEMORY_WORKFLOW.md).

Read this file before changing memory, recall, tools, extraction, prompts, or DB schema.

---

## Scope

Memory = **knowledge graph** (`knowledge_graph.py`) + **recall** (`memory_recall.py`) + **tools** (`tools/memory_tools.py`) + **optional batch** (`memory_extraction.py`, `dream_cycle.py`). Thread chat (`threads.py`) is separate storage.

---

## Invariants (do not break without explicit approval)

1. **Single recall path** for inject + `search_memory`: `memory_recall.recall_memories()` / `recall_from_user_messages()`. Do not add parallel recall logic in `agent_context` for production inject.
2. **DB schema changes** require user approval per workspace rule `db-change-approval-and-schema-review.mdc`.
3. **No silent fallbacks** that download models at runtime.
4. **Category validation:** `save_entity` uses `resolve_entity_type()` in `knowledge_graph.py`; tools use `memory_tools._resolve_category()`. Extend `ENTITY_TYPE_ALIASES` for model mistakes; do not widen `VALID_ENTITY_TYPES` casually.
5. **CLI does not start** `start_periodic_extraction` or `start_dream_loop` — document if adding, do not assume running.
6. **`list_memories("")`** must list all types; invalid filter must not return "No memories stored" when graph is non-empty.
7. **Relation type banning:** `add_relation()` silently returns `None` for banned types (`related_to`, `associated_with`, `connected_to`, `linked_to`, `has_relation`, `involves`, `correlates_with`). Tools must check for `None` return and provide a useful error.
8. **`capture_save_memory_calls()`** in `memory_import_runner.py` now yields `(saves, links)` tuple — callers must unpack both.

---

## Valid entity types

```text
VALID_ENTITY_TYPES = {
  concept, event, fact, media, organisation, person, place,
  preference, project, self_knowledge, skill
}
```

**Aliases (normalize before validate):** `ENTITY_TYPE_ALIASES` in `knowledge_graph.py` — includes `personal`→`fact`, `preferences`→`preference`, `family`→`person`, etc.

**Tool-facing hints:** `memory_tools._VALID_TYPES_HINT`, `format_valid_entity_types()`.

---

## Valid relation types

`add_relation()` accepts any snake_case label not in the banned set, but warns on unknown types. `VALID_RELATION_TYPES` in `knowledge_graph.py` is the canonical set. The system prompt instructs the model to use these common types:

```
father_of, mother_of, sibling_of, child_of, spouse_of, friend_of, colleague_of, knows,
works_at, lives_in, born_in, employed_by, manages, founded, works_on,
prefers, enjoys, dislikes, interested_in, has_skill, learning, uses, created_by, owns
```

**Banned (blocked by `add_relation`, not just in prompts):**
```
related_to, associated_with, connected_to, linked_to, has_relation, involves, correlates_with
```

---

## Entry points (file → function)

| Concern | File | Symbol |
|---------|------|--------|
| Turn instructions + inject | `agent_runtime.py` | `_compose_instructions`, `_instructions_text` |
| Recall query build | `memory_layer.py` | `recall_context_for_turn_with_meta` |
| Recall core | `memory_recall.py` | `recall_memories`, `recall_from_user_messages` |
| Graph CRUD | `memory.py` | `save_memory`, `list_memories`, `update_memory`, … |
| Graph engine | `knowledge_graph.py` | `save_entity`, `list_entities`, `graph_enhanced_recall`, `semantic_search`, `add_relation`, `get_relations`, `get_neighbors`, `to_mermaid` |
| Agent tools | `tools/memory_tools.py` | `save_memory_entry`, `list_memories`, `search_memory`, `link_memories_entities`, `update_memory_entry`, `explore_connections_for_entity` |
| Entity/name resolution | `tools/memory_tools.py` | `_resolve_entity(name_or_id)` |
| Tool registration | `agent_runtime.py` | `_register_tools` |
| Tool catalog | `agent_runtime.py` | `AGENT_TOOL_CATALOG` |
| Batch extract | `memory_extraction.py` | `run_extraction`, `_extract_from_conversation`, `_dedup_and_save`, `_resolve_relation_endpoint`, `_merge_aliases` |
| Contradiction check | `validation.py` | `check_contradiction` (LLM-based, lazy import) |
| Dream | `dream_cycle.py` | `run_dream_cycle`, `start_dream_loop`, `_should_dream` |
| Dream phases | `dream_cycle.py` | `_run_merge_phase`, `_run_enrichment_phase`, `_run_decay_phase`, `_run_inference_phase`, `_run_insights_phase` |
| Rejection cache | `dream_cycle.py` | `_record_rejection`, `_is_pair_recently_rejected` |
| One-shot LLM (extract/dream) | `llm_runner.py` | `run_text_completion` |
| Thread persistence | `threads.py` | `append_turn_messages`, `thread_conversation_rows`, `list_threads` |
| Import verification | `memory_import_runner.py` | `capture_save_memory_calls` (yields `(saves, links)`), `FactsImportResult` |
| Trace | `agent_trace.py` | `trace_routing_snapshot`, `trace_llm_wire_http` |

---

## Read path (every `run_turn`)

```
run_turn
  → _compose_instructions(deps, user_text)
      → assemble_context(thread_id, user_text)  # context_layer.py
          → recent_user_messages: last 3 user contents from thread DB
      → recall_context_for_turn_with_meta(recent_user_messages, user_text)
          → recall_from_user_messages
              → recall_memories(joined query)
                  1. graph_enhanced_recall (threshold 0.35, hops 1)
                  2. search_entities (SQL LIKE)
                  3. list_entities (fallback)
      → append to instructions: "You KNOW the following facts…"
  → Agent.run_sync(user_text, message_history=history)
```

**Meta in trace:** `recall_path`, `recall_query`, `injected_subjects` in `ROUTING SNAPSHOT`.

**Not in `ModelMessage` history:** instructions + inject are via `@agent.instructions` callback. Full HTTP body: `log_llm_wire=true` → `LLM WIRE REQUEST`.

---

## Write paths

| Path | Trigger | LLM? | `source` tag |
|------|---------|------|----------------|
| `save_memory` tool | Model tool call | No | `live` |
| `link_memories` tool | Model tool call | No | `live` |
| `update_memory` tool | Model tool call | No | `live` |
| `memory_extraction.run_extraction` | Manual / periodic | Yes (`EXTRACTION_PROMPT`) | `extraction` |
| `dream_cycle` Phase 1 merge | Scheduled loop | Yes (`DREAM_MERGE_PROMPT`) | `dream_merge` |
| `dream_cycle` Phase 2 enrich | Scheduled loop | Yes (`DREAM_ENRICH_PROMPT`) | _(entity update)_ |
| `dream_cycle` Phase 4 infer | Scheduled loop | Yes (`DREAM_INFER_PROMPT`) | `dream_infer` |

**After batch writes:** `kg.rebuild_index()` when `total_saved > 0`. Live saves reindex per entity unless `kg._skip_reindex` is `True` during batch. Callers of `_dedup_and_save()` must call `kg.rebuild_index()` themselves if they need a fresh FAISS index immediately (tests must do this).

---

## Tool contracts (`tools/memory_tools.py`)

- **Return type:** `str` (JSON or human-readable lines). pydantic-ai passes string back to model.
- **Errors:** Raise `ToolError("…")` — caught in `_trace_tool_invoke`, logged, re-raised.
- **`list_memories`:** Invalid category → message with valid types (not exception).
- **`save_memory` docstring** in `agent_runtime.py` must list valid categories (feeds tool schema).

### `link_memories_entities(source_id, target_id, relation_type)`

1. Calls `_resolve_entity(name)`: `kg.find_by_subject(None, name)` then `kg.get_entity(id)` fallback
2. Each endpoint: one 0.5 s retry if not found (parallel `save_memory` race guard)
3. Pre-checks banned relation type and self-loop before calling `add_relation()`
4. `add_relation()` returns `None` for duplicate edge (idempotent) → returns `"Relation already exists"` string (not an error)
5. Returns `"Relationship created.\n{src} --[{type}]--> {tgt}\nRelation ID: {id}"` on success

### `update_memory_entry(memory_id, content, subject, aliases, tags, category)`

- Thin wrapper over `memory.update_memory()`
- Only passes kwargs with non-empty values (preserves existing fields)
- Returns JSON of updated entity dict
- `None` from `update_memory` → `ToolError("not found")`

### `explore_connections_for_entity(entity_id, hops)`

- Resolves by name or ID via `_resolve_entity()`
- `hops` capped at 3
- Calls `kg.get_relations()` (direct edges) + `kg.get_neighbors()` (multi-hop)
- Appends `kg.to_mermaid()` diagram when graph has edges (skipped for isolated entity)

---

## Extraction internals (`memory_extraction.py`)

### `_dedup_and_save(extracted, source)` — returns `(saved, contradictions, low_conf_skipped)`

**Entity pass:**
1. For each `{category, subject, content}` entry: `find_by_subject` → optional FAISS fallback at threshold 0.80
2. If existing: read `aliases`, call `_merge_aliases(existing, new_aliases)`, register all aliases in `subject_to_id` map
3. Contradiction check via `validation.check_contradiction()` (LLM-based, lazy import)
4. If no conflict: merge content strings

**Relation pass (after entity pass):**
1. Skip banned types (`_VAGUE_RELATION_TYPES`)
2. Skip `confidence < 0.80` (`_MIN_RELATION_CONFIDENCE`)
3. Resolve endpoints via `_resolve_relation_endpoint(name, subject_to_id, source)`:
   - `subject_to_id` map (includes aliases registered in entity pass)
   - `find_by_subject` exact match
   - `kg.semantic_search(name, threshold=0.80)` with cross-source guard (raises to 0.90 when `source` and hit source differ in `document:` prefix)

### `run_extraction()` — thread selection

- Skip `wf-*` thread IDs (workflow internals, not user facts)
- Skip threads with no user messages
- Skip threads with `updated_at ≤ last_extraction`

### Journal format

```json
{
  "timestamp": "2026-05-28T02:00:00",
  "threads_scanned": 3,
  "entities_saved": 12,
  "contradictions_blocked": 1,
  "low_confidence_skipped": 2,
  "thread_details": [
    {"thread": "abc123", "extracted": 8, "saved": 4, "contradictions_blocked": 1, "low_confidence_skipped": 0}
  ]
}
```

---

## Dream cycle internals (`dream_cycle.py`)

### `_should_dream(cfg)` guard

All five conditions must be true:
1. `cfg["enabled"] == True`
2. `window_start <= now.hour < window_end`
3. `_already_ran_today()` is `False` (reads `dream_journal.json`)
4. `_is_idle()` — `memory_extraction._active_threads` is empty
5. `_is_ollama_busy()` — `GET http://{llm_host}:{llm_port}/api/ps` returns `num_requests == 0`

### Phase 1 — Merge (`_run_merge_phase`)

- `semantic_search(query, top_k=3, threshold=cfg.merge_threshold)` per entity in batch
- **Name guard:** if `subj_a` and `subj_b` do not overlap as substrings → require score ≥ 0.98 (not just 0.93)
- Never merge entity with `subject.lower() == "user"`
- After merge: `kg.update_entity(survivor_id, merged_desc, aliases=_union_aliases(survivor, duplicate))`
- Re-point relations from duplicate to survivor; skip self-loops
- **Batch rotation:** `batch_offset` persisted in `dream_config.json`, advances by `batch_size // 2` each cycle

### Phase 2 — Enrichment (`_run_enrichment_phase`)

- Targets entities with `len(description) < 80` and `subject != "User"`
- Requires ≥ 2 conversation excerpts as evidence (`_find_conversation_mentions`)
- Validation before writing: contamination check (no other entity subjects in new text), groundedness ≥ 40%, new length > old length

### Phase 3 — Decay (`_run_decay_phase`)

- Query: `source='dream_infer' AND updated_at < (now - 90 days)`
- `new_conf = round(conf * 0.90, 4)`
- Prune when `new_conf < 0.30`
- Returns `(decayed, pruned, details_list)` for journal

### Phase 4 — Inference (`_run_inference_phase`)

- `_find_cooccurring_pairs(batch)`:
  - Build `re.compile(r"\b(subject|alias1|alias2)\b")` per entity
  - Scan all threads; count pair co-occurrences by thread
  - Apply hub cap (`_HUB_CAP = 3`): skip if entity already in 3 candidate pairs
  - Skip: `_is_pair_recently_rejected`, description cross-mentions, existing edge
- `_infer_relation(a, b, excerpt, co_count)`:
  - Tautology guard: skip if `subj_a in subj_b` or `subj_b in subj_a`
  - On `has_relation: false` → `_record_rejection(a_id, b_id)` (7-day TTL)
  - On success: store `evidence` and `co_occurrences` in relation `properties`

### Phase 5 — Insights (`_run_insights_phase`)

- `_collect_system_snapshot()` gathers: KG stats, last extraction journal, last dream journal, active workflows
- Calls `DREAM_INSIGHTS_PROMPT` with snapshot
- Parses JSON array of insight objects; logs each at `INFO`

### Rejection cache (`dream_rejections.json`)

```json
{
  "entity_aaa__entity_bbb": "2026-05-28T02:15:00+00:00"
}
```

Key format: `sorted(id_a, id_b)` joined with `__`. TTL: 7 days. Cleaned up on each write.

---

## `memory_import_runner.py` API changes

`capture_save_memory_calls()` now yields a **tuple** `(saves: list[SaveMemoryRecord], links: list[LinkMemoryRecord])`.

```python
with capture_save_memory_calls() as (saves, links):
    run_turn(...)

ok_saves = sum(1 for s in saves if s.error is None and s.verified_in_db)
ok_links = sum(1 for lk in links if lk.error is None and lk.verified_created)
```

`FactsImportResult` new fields: `link_memory_attempts`, `link_memory_ok`, `relation_count_before`, `relation_count_after`.

Verification: if `link_memory_attempts > 0` and `relation_count_after <= relation_count_before`, an error is added.

---

## Validation (`validation.py`)

`check_contradiction(old_content, new_content, subject) → str | None`

- **Was:** regex number comparison
- **Now:** `run_text_completion(load_config(), _CONTRADICTION_PROMPT.format(...))` — LLM-based semantic check
- Returns conflict description string on YES, `None` on NO
- Falls back to `None` (allow merge) on any exception — lazy imports avoid circular dependency chain `validation ← memory_extraction ← agent_runtime`

---

## Environment / config

| Variable / key | Effect |
|----------------|--------|
| `BEST_BUDDY_AGENT_DATA_DIR` | `memory.db`, FAISS, extraction/dream state, rejection cache |
| `BEST_BUDDY_AGENT_CONF` | Config path |
| `[logging] log_llm_wire` | Exact Ollama JSON in trace |
| `[prompts] language` | Prompt bundle under `conf/prompts/{language}/` (live agent, tools, extract, dream) |
| `agent_system_prompt_file` | Optional override for `agent_system.txt` only (path relative to conf dir) |
| `max_tool_iterations` | Tool loop cap |
| `dream_config.json` | Dream enabled, window, thresholds, `batch_offset` |

---

## Embedding / recall pitfalls

- **Best Buddy:** `LocalHashEmbedding` — poor cross-language semantic match. Expect `recall_path: list_recent` often for non-English queries.
- **Do not assume** semantic recall matched user language.
- **Thoth** used `Qwen3-Embedding-0.6B`; different index format, not compatible without rebuild.
- **After `_dedup_and_save`:** FAISS is stale until `kg.rebuild_index()` is called. Tests that call `_dedup_and_save()` directly must call `kg.rebuild_index()` before any subsequent `semantic_search` call.

---

## Tests to run after memory changes

```bash
# Core tools and relations
.venv/bin/pytest tests/test_memory_tools_graph.py -q

# Extraction quality: alias, FAISS fallback, cross-source, workflow filter
.venv/bin/pytest tests/test_extraction_quality.py -q

# Dream cycle: all phases, rejection cache, name guard
.venv/bin/pytest tests/test_dream_cycle.py -q

# Existing core tests
.venv/bin/pytest tests/test_memory_core.py -q
.venv/bin/pytest tests/test_memory_context.py -q
.venv/bin/pytest tests/test_agent_runtime.py -q
.venv/bin/pytest tests/test_memory_import_runner.py -q

# Full suite (no Ollama)
.venv/bin/pytest tests/ -q
```

---

## Common bugs (symptom → check)

| Symptom | Likely cause |
|---------|----------------|
| Rich answer, empty `list_memories` | No write; only thread history used |
| `link_memories` "Source entity not found" | Entity not saved yet; or subject name mismatch (check aliases) |
| `link_memories` "too vague" error | Used `related_to` or other banned type |
| `link_memories` returns "Relation already exists" | Duplicate call — idempotent, not an error |
| Graph has edges but recall ignores them | Recall uses FAISS threshold 0.35 × decay; try `recall_path` in trace |
| Extraction creates duplicate entities | Two entities saved with different subjects for the same person; dream Phase 1 merges these nightly if similarity ≥ 0.93 |
| Dream Phase 1 merges wrong entities | Name guard not triggered — check if subjects overlap; if not, requires score 0.98 |
| `check_contradiction` returns None in test | LLM not running; falls back silently — expected behaviour in unit tests |
| `capture_save_memory_calls()` TypeError | Old code using `as saves` instead of `as (saves, links)` |
| `test_semantic_hit_avoids_list_recent` fails with all tests | Other tests left stale FAISS index; call `kg.rebuild_index()` after `_dedup_and_save()` in tests |

---

## When implementing features

- **New write path:** Prefer `memory.save_memory` / `kg.save_entity` with valid `source` string.
- **New read path:** Extend `recall_memories` only with schema-wide review.
- **New tool:** Register in `_register_tools()` + add `conf/prompts/{language}/tools/{name}.txt` + update `agent_system.txt`.
- **Prompt changes:** Edit files under `conf/prompts/{language}/` (see `prompt_loader.py` registry).
- **Do not** add second venv; use project `.venv`.
- **Fallbacks** (e.g. auto-map unknown category silently): need user approval per `approval-for-fallbacks.mdc`.

---

## Related files (quick map)

```
best-buddy-agent/src/best_buddy_agent/
  memory_recall.py        # recall pipeline + format_for_system_prompt
  memory_layer.py         # thin wrapper for turn inject
  memory.py               # legacy API → knowledge_graph
  knowledge_graph.py      # SQLite, FAISS, NetworkX, VALID_ENTITY_TYPES, add_relation, get_relations
  memory_extraction.py    # batch LLM extract, alias merging, FAISS fallback, wf- filter
  validation.py           # check_contradiction (LLM-based)
  dream_cycle.py          # full 5-phase maintenance loop + rejection cache
  agent_runtime.py        # Agent, tools, compose instructions, AGENT_TOOL_CATALOG
  tools/memory_tools.py   # tool surface: save, link, update, explore, search, list, get, delete
  context_layer.py        # recent_user_messages for recall query
  threads.py              # chat history ≠ memory
  llm_runner.py           # extraction/dream LLM calls (run_text_completion)
  agent_trace.py          # ROUTING SNAPSHOT, LLM WIRE
  memory_import_runner.py # scripted import: capture_save_memory_calls → (saves, links)
  prompt_loader.py        # PromptCatalog: loads conf/prompts/{language}/

conf/prompts/{language}/  # all LLM prompts (agent_system, import_turn, tools/, dream/, …)

tests/
  test_memory_tools_graph.py   # link, update, explore tools
  test_extraction_quality.py   # alias merging, FAISS fallback, cross-source, wf- filter
  test_dream_cycle.py          # 5 phases, rejection cache, name guard
  test_memory_core.py          # save, list, get, delete, relations
  test_memory_context.py       # recall paths
  test_memory_import_runner.py # capture_save_memory_calls, FactsImportResult
```

---

## Cross-links

- [MEMORY_WORKFLOW.md](MEMORY_WORKFLOW.md) — developer narrative with examples
- [DEBUGGING.md](DEBUGGING.md) — trace blocks
- [ARCHITECTURE.md](ARCHITECTURE.md) — high-level diagram
- [THOTH_EXTRACTION_MAP.md](THOTH_EXTRACTION_MAP.md) — provenance
