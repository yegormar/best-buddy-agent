# Best Buddy Memory — Architecture Diagram Generation Prompt

Feed the sections below (Style + Diagram Content + Footer) into an image-generation AI to produce a diagram similar in layout and polish to **Thoth Core Agent Architecture** (`Thoth/docs/Core_Agent_arch.jpg`) and the generated **Best Buddy Memory Architecture** poster (`docs/best_buddy_memory_architecture.png`).

---

## Section 1: Visual Style and Aesthetic

Create a sophisticated, modern **dark-mode** architecture poster. Clean, professional, highly organized — suitable for technical documentation or a README hero image.

### Color palette

| Role | Color |
|------|-------|
| Background | Deep charcoal or very dark blue-black (#0d1117 – #12141a) |
| Primary text & connector lines | Warm gold / cream (#e8c872 – #f5e6c8) |
| **Gold / Yellow** | Orchestration & recall (read path) |
| **Orange** | Write paths (tools, extraction, dream) |
| **Purple** | Knowledge graph & entity model |
| **Grey** | Storage & infrastructure |
| **Blue-grey** | Thread store (separate from long-term memory) |
| **Reddish-pink / coral** | Safety, validation, HITL |

### Typography

- **Main title** (top center): Large elegant serif — *"Best Buddy Memory Architecture"*
- **Subtitle** (below title): Smaller sans-serif — *"Knowledge Graph — SQLite + NetworkX + FAISS"*
- **Module headers**: Bold sans-serif — e.g. *"Read Path (Every Turn)"*, *"Write Paths"*
- **Body / list items**: Small legible sans-serif

### Iconography

Minimalist **line icons** (stroke only, no fill):
- Chat bubbles for thread store
- Database cylinder for SQLite
- Graph nodes/edges for NetworkX
- Vector/search for FAISS
- Brain for recall pipeline
- Pencil/save for write tools
- Moon/clock for dream cycle
- Shield for validation and HITL delete
- Link chain for relations

### Layout & connectors

- **Central hub**: large purple/gold bordered box — *"Knowledge Graph Engine (knowledge_graph.py)"*
- **Top banner**: two-store mental model (thread vs graph)
- **Left column**: read path (gold)
- **Right column**: write paths (orange, some dashed for background)
- **Arrows**:
  - **Solid gold** — read / inject flow
  - **Solid orange** — live write / persist
  - **Dashed orange** — background batch (extraction, dream)
- **Bottom row**: storage, entity model, safety

### Canvas

- Landscape orientation, ~16:9
- Legend bottom-right; 7-step flow bottom-left; arrow key top-right

---

## Section 2: Diagram Structure and Content

### Top banner — Two-store mental model

Two side-by-side boxes with a connecting label:

| Box | Color | Contents |
|-----|-------|----------|
| **Thread Store (`threads.db`)** | Blue-grey | Conversation continuity, recent user messages, **NOT long-term memory** |
| **Knowledge Graph (`memory.db`)** | Purple | Durable facts & relations, entities + edges, FAISS semantic index |

**Label between them:** *"Chat is not memory — facts must be written to graph"*

---

### Central hub — Knowledge Graph Engine (`knowledge_graph.py`)

**Largest box, center.** Purple accent with gold inner highlights.

Internal list (each with icon):

| Item | Detail |
|------|--------|
| SQLite WAL | Durable store (source of truth) |
| NetworkX MultiDiGraph | In-memory mirror, rebuilt on startup |
| FAISS vector index | `LocalHashEmbedding` (not Qwen embedding) |
| Entity types | person, place, preference, project, event, fact, skill, … |
| Relation types | father_of, works_at, lives_in, prefers, … |
| Memory decay | `_decay_multiplier` — recent/recalled score higher |
| Recall reinforcement | `recalled_at` touched on successful recall |

**Callout box (gold, attached to hub):** *Graph-Enhanced Recall*
`FAISS seeds` → `decay multiplier` → `1-hop neighbors` → `cap max_results` → `touch recalled_at`

---

### Left column — Read Path (Every Turn)

Gold accent. Numbered vertical flow:

1. **User message arrives** (from chat turn)
2. **`assemble_context`** — last 3 user lines from `threads.db`
3. **`memory_recall.recall_memories`** — query built from recent messages + current text
4. **Pipeline** (nested box with 3 steps):
   - **Step 1 — semantic:** `graph_enhanced_recall` — FAISS search + 1-hop graph expansion + decay multiplier
   - **Step 2 — keyword:** `search_entities` — SQL `LIKE` on subject/description/tags
   - **Step 3 — list_recent:** bounded `list_entities` fallback if both miss
5. **Inject** into Agent Runtime instructions:
   ```text
   You KNOW the following facts from long-term memory:
   - [id=a1b2c3] [person] Alice: ...
   ```

Solid gold arrow: Read Path → Knowledge Graph Engine → Agent Runtime (inject)

**Note callout:** Cross-language queries often miss FAISS with `LocalHashEmbedding`; step 3 is the safety net.

---

### Right column — Write Paths

Orange accent. Three stacked boxes:

#### A. Agent Tools (Live Chat)

Always-on writes during `run_turn`. Icons per tool:

| Tool | Effect | HITL |
|------|--------|------|
| `search_memory` | Same recall core as inject | no |
| `list_memories`, `get_memory` | Read entities | no |
| `save_memory` | Create/merge entity | no |
| `link_memories` | Typed relation between entities | no |
| `update_memory` | Correct existing entity | no |
| `explore_connections` | Graph traversal + Mermaid | no |
| `delete_memory` | Remove entity | **yes** |

**Example callout:** save Andrey (person) + link `child_of` User + link `study_at` Ottawa

Solid orange arrows → Knowledge Graph Engine

#### B. Background Extraction (`memory_extraction.py`)

Dashed orange border — scheduled or manual, **not started by CLI by default**.

- Scan threads updated since `last_extraction`
- LLM `EXTRACTION_PROMPT` → JSON facts
- Dedup, alias merging, FAISS relation fallback
- Contradiction check (`validation.py`)
- Skip `wf-*` workflow threads
- Output: `extraction_journal.json`

Dashed orange arrow → Knowledge Graph Engine

#### C. Dream Cycle (`dream_cycle.py`)

Dashed orange border — nightly 1–5 AM when idle.

**Guards:** enabled, time window, not run today, no active threads, Ollama not busy

**Five phases:**
1. Duplicate merge (name guard, alias promotion)
2. Enrichment (thin descriptions from conversation evidence)
3. Confidence decay (inferred edges fade; prune at 0.30)
4. Relation inference (co-occurrence + rejection cache)
5. Insights (LLM health snapshot)

Output: `dream_journal.json`, `dream_rejections.json`

Dashed orange arrow → Knowledge Graph Engine

---

### Bottom left — Local Storage

Grey accent. Two columns:

**App Data** (`~/.best_buddy_agent` or `BEST_BUDDY_AGENT_DATA_DIR`)

| File | Role |
|------|------|
| `memory.db` | Entities + relations (SQLite) |
| `memory_vectors/index.faiss` | Semantic index |
| `extraction_journal.json` | Extraction run history |
| `dream_journal.json` | Dream cycle history |
| `dream_config.json` | Dream settings |
| `dream_rejections.json` | Rejected inference pairs |

**Separate (not recall source)**

| File | Role |
|------|------|
| `threads.db` | Chat messages only |

---

### Bottom center — Entity Model

Purple accent. Small box with mini graph diagram:

**Entity node:** `id`, `subject`, `category`, `description`, `aliases`, `properties`, `tags`

**Relation edge:** `source_id` → `relation_type` → `target_id`

**Visual example graph:**
```text
User --child_of--> Andrey --study_at--> Ottawa
```

---

### Bottom right — Safety & Quality

Pink accent. Two columns:

**Left — Policies**
- Category validation (`VALID_ENTITY_TYPES` + `ENTITY_TYPE_ALIASES`)
- Banned vague relations: `related_to`, `associated_with`, `connected_to`, …
- `delete_memory` requires HITL approval
- Contradiction check before save (extraction)
- Cross-source FAISS threshold 0.90 vs same-source 0.80

**Right — Invariants**
- Single recall path: `memory_recall.py` only (no parallel inject logic)
- Writes: SQLite first → NetworkX → FAISS rebuild
- `list_memories("")` must list all types when graph non-empty

---

## Section 3: Footer, Legend, and Flow Summary

### Legend (bottom-right)

| Color | Category |
|-------|----------|
| Gold | Orchestration / recall |
| Orange | Write paths |
| Purple | Knowledge graph |
| Grey | Storage |
| Blue-grey | Thread chat (separate store) |
| Pink | Safety & validation |

### Arrow key (top-right)

| Style | Meaning |
|-------|---------|
| Solid gold | Read / inject |
| Solid orange | Live write / persist |
| Dashed orange | Background batch |

### Flow summary (bottom-left, 7 steps)

1. User speaks in chat → thread stored in `threads.db`
2. Recall query built from recent user messages
3. Semantic → keyword → fallback search against knowledge graph
4. Matching facts injected into LLM context ("You KNOW…")
5. Model may call memory tools to read, save, link, or update
6. Writes persist: SQLite → NetworkX → FAISS index
7. Background extraction and dream cycle curate graph overnight

---

## Section 4: One-Paragraph Image AI Prompt (condensed)

*Optional single-block prompt:*

> Dark-mode technical architecture poster titled "Best Buddy Memory Architecture" subtitle "Knowledge Graph SQLite + NetworkX + FAISS". Top banner two-store model: threads.db chat only vs memory.db durable facts with label "Chat is not memory". Central large purple hub Knowledge Graph Engine with SQLite WAL NetworkX FAISS LocalHashEmbedding entity types relation types memory decay. Left gold Read Path numbered flow assemble_context memory_recall 3-step pipeline semantic keyword list_recent inject You KNOW facts. Right orange Write Paths three boxes: Agent Tools save_memory link_memories delete approval, Background Extraction dashed, Dream Cycle 5 phases dashed nightly. Bottom grey Local Storage memory.db index.faiss journals, separate threads.db. Bottom center Entity Model mini graph User child_of Andrey study_at Ottawa. Bottom right pink Safety category validation banned relations HITL delete single recall path. Gold solid read arrows orange solid write dashed orange background. Footer 7-step flow and color legend. Style like Thoth architecture poster elegant serif title sans-serif labels minimalist icons warm gold on charcoal.
