# Best Buddy Agent — Architecture Diagram Generation Prompt

Feed the sections below (Style + Diagram Content + Footer) into an image-generation AI to produce a diagram similar in layout and polish to **Thoth Core Agent Architecture** (`Thoth/docs/Core_Agent_arch.jpg`), but accurately representing **Best Buddy Agent v0.2 (pydantic-ai)**.

---

## Section 1: Visual Style and Aesthetic

Create a sophisticated, modern **dark-mode** architecture poster. Clean, professional, highly organized — suitable for technical documentation or a README hero image.

### Color palette

| Role | Color |
|------|-------|
| Background | Deep charcoal or very dark blue-black (#0d1117 – #12141a) |
| Primary text & connector lines | Warm gold / cream (#e8c872 – #f5e6c8) |
| **Gold / Yellow** | Core orchestration & agent runtime |
| **Orange** | Tools & execution |
| **Purple** | Memory & context |
| **Grey** | Storage, config, infrastructure |
| **Reddish-pink / coral** | Safety, governance, human approval |

### Typography

- **Main title** (top center): Large elegant serif — *"Best Buddy Agent Architecture"*
- **Subtitle** (below title): Smaller sans-serif — *"v0.2 — pydantic-ai + local Ollama (no LangChain)"*
- **Module headers**: Bold sans-serif, numbered — e.g. *"1. User Interfaces / Channels"*
- **Body / list items**: Small legible sans-serif

### Iconography

Every list item and major module gets a simple minimalist **line icon** (stroke only, no fill):
- Terminal for CLI
- Paper plane / chat bubble for Telegram
- Brain or loop for reasoning
- Database cylinder for SQLite
- Shield for approval gates
- Clock for workflows / reminders
- Envelope for Gmail
- Calendar for Google Calendar
- Globe for web search
- Image/eye for vision
- Microphone for STT

### Layout & connectors

- **Hierarchical yet interconnected** — central hub with satellite modules
- **Central hub**: large rounded rectangle — *"Agent Runtime (pydantic-ai)"*
- **Module boxes**: Thin gold borders, slightly rounded corners, subtle inner padding
- **Arrows**:
  - **Solid gold** — primary request/response flow
  - **Dashed gold** — background / scheduled / async flow
  - **Dotted pink** — untrusted external input (web fetch, Gmail content, tool results)
- **Dashed grey boundary box** around *External Services* (Ollama host, Telegram API, Google APIs, DuckDuckGo)

### Canvas

- Landscape orientation, ~16:9 or 3:2
- Generous margins; no clutter
- Legend bottom-right; flow summary bottom-left; arrow key top-right

---

## Section 2: Diagram Structure and Content

### Central hub — Agent Runtime (pydantic-ai)

**Largest box, center of diagram.** Gold accent border.

Internal vertical list (each with icon):

| Item | Description |
|------|-------------|
| Context assembly | `assemble_context` + memory recall injection |
| Instructions composer | Language prompts from `conf/prompts/{en,ru}/` |
| Reasoning loop | pydantic-ai Agent → Ollama via OpenAI-compatible API |
| Tool routing | Conditional tool registration from `AgentConfig` |
| Deferred approval (HITL) | `write_file`, `delete_memory`, Gmail draft, Calendar writes |
| Response synthesis | `run_turn` / `resume_turn` → channel reply |
| Trace logging | Local `agent-trace.log` (optional, copy-paste blocks) |

**Connected modules** (solid gold arrows in/out of hub):
- Left: Context Layer, Memory System, Thread Store
- Top: User Channels, Model Layer
- Right: Native Tool Layer
- Bottom: Task Engine, Local Storage, Safety & Control

Thin delegate box *"orchestrator.py"* (dashed, small) pointing into hub: *"thin delegate → run_turn()"*

---

### 1. User Interfaces / Channels (top-left)

Horizontal row of entry points:

| Channel | Details |
|---------|---------|
| **CLI** (`best-buddy-agent-chat`) | Interactive terminal; thread id `cli-main` |
| **Telegram** (`best-buddy-agent-telegram`) | Long polling; single allowed user; Markdown→HTML formatting |

**Telegram sub-capabilities** (small nested row or callout under Telegram icon):

| Capability | Component |
|------------|-----------|
| Text chat | `channels/telegram.py` → `chat_once` |
| Voice / audio | `[stt]` faster-whisper (local, read-only HF cache) |
| Photos | `[vision]` native multimodal → Ollama; `vision_cache/` |
| Proactive notify | `telegram_notifier` — reminders, deadline proposals |
| Inline approval | Approve / Deny buttons for HITL tools |

Arrow: Channels → `runtime.chat_once` → Agent Runtime (solid gold)

---

### 2. Model Layer (top-right)

**Single provider focus** (unlike multi-cloud Thoth):

| Component | Label |
|-----------|-------|
| **Ollama** (primary) | Local or remote GPU host (`llm_host:llm_port`) |
| Model config | `llm_model`, `llm_num_ctx`, `llm_think`, temperature, keep-alive |
| Vision capability | Required for `[vision]` — checked at startup |
| OpenAI-compatible client | pydantic-ai `OllamaModel` — no LangChain |

Sub-label under icons: *"Model factory + optional reliability capabilities"*

Arrow: Agent Runtime ↔ Ollama (bidirectional solid gold, crosses external boundary)

**Optional reliability strip** (small grey box attached to Model Layer):
- Summarization near 85% context window
- PatchToolCalls, StuckLoopDetection (pydantic-deep)

---

### 3. Context Layer (left, below channels)

Vertical list:

- Active conversation (recent turns, max 12)
- Auto-recalled memories (injected block)
- Workflow context (when running inside a workflow step)
- Tool results (mark as **untrusted** — dotted pink arrow into hub)
- Thread message history (pydantic-ai `ModelMessage` list)
- Gmail / web / calendar / vision availability fragments (from prompt catalog)

Arrow: Context Layer → Agent Runtime (solid gold)

---

### 4. Memory System (left, below context)

Purple accent. Vertical list:

| Component | Technology |
|-----------|------------|
| Knowledge graph | SQLite + NetworkX |
| Semantic index | FAISS (`memory_vectors/`) — `LocalHashEmbedding` |
| Entities & relations | Categories, tags, aliases, graph edges |
| Auto-recall pipeline | ① FAISS+graph ② keyword SQL ③ recent fallback |
| Memory tools | `search_memory`, `save_memory`, `list_memories`, `get_memory`, `link_memories`, `update_memory`, `explore_connections` |
| Background curation | `memory_extraction.py` |
| Dream cycle | `dream_cycle.py` (nightly consolidation) |

Arrow: Memory System ↔ Agent Runtime (bidirectional; recall in, save/update out)

---

### 5. Thread Store (left, bottom of memory column)

Grey accent. Small box:

- `threads.db` — per-conversation history
- Thread ids: `cli-main`, `telegram:dm:<chat_id>`, workflow threads
- Vision: pixels stripped after turn; cache filename only in history

---

### 6. Tool Router (between hub and tools, right side)

Small orange box:

- Classify & route tool calls (pydantic-ai `@agent.tool`)
- Conditional load: Gmail ready, Calendar ready, `[web]`, `[vision]`
- Enforce `requires_approval` on destructive writes
- Tool descriptions from `conf/prompts/{lang}/tools/*.txt`

Arrow: Agent Runtime → Tool Router → Native Tool Layer

---

### 7. Native Tool Layer — Built-in Tools (right column)

Orange accent. Long vertical grouped list:

**Filesystem** (always)
- `read_file`, `list_files`, `write_file` ⚠ approval

**Memory** (always)
- `search_memory`, `save_memory`, `list_memories`, `get_memory`
- `delete_memory` ⚠ · `link_memories` · `update_memory` · `explore_connections`

**Workflows** (always)
- `list_workflows`, `create_workflow`, `update_workflow`, `delete_workflow`
- `trigger_workflow`, `run_workflow_now`, `workflow_run_status`
- `create_reminder`

**Gmail** (when OAuth ready) — *no send tool*
- `search_gmail`, `get_gmail_message`, `get_gmail_thread`
- `create_gmail_draft` ⚠ approval

**Calendar** (when OAuth ready)
- `get_current_datetime`, `search_events`
- `create_calendar_event` ⚠ · `update_calendar_event` ⚠

**Web** (when `[web] enabled`)
- `web_search` (DuckDuckGo) · `fetch_url`

**Vision** (when `[vision] enabled`)
- `revisit_image` (reload cached photo for follow-up questions)

⚠ = human-in-the-loop approval required

Arrows: Tools → Agent Runtime (dotted pink — *untrusted results*)

---

### 8. External Services (right edge, inside dashed grey trust boundary)

| Service | Used for |
|---------|----------|
| Ollama HTTP | LLM inference (`:11434`) |
| `api.telegram.org` | Bot long polling + proactive sends |
| Gmail API | Read + drafts only |
| Google Calendar API | Read + write (with approval) |
| DuckDuckGo | Web search |
| Arbitrary HTTPS | `fetch_url` |

Label on boundary: *"Outbound HTTPS — no inbound ports"*

---

### 9. Task Engine (bottom center)

Gold/orange accent. Vertical list:

| Component | Role |
|-----------|------|
| Workflow scheduler | `workflow_engine.py` — poll loop started by Telegram bot |
| Step types | `prompt`, `condition`, `approval`, `subtask`, `notify`, `function` |
| Schedules | `interval`, `daily`, `once` |
| `notify_only` workflows | Telegram reminders without LLM |
| **Deadline Watch** | Gmail scan → LLM extract → Telegram proposal → approve → schedule reminders |
| `deadline-watch-scan` | Seeded function workflow (`services/bootstrap.py`) |

**Deadline Watch flow** (small numbered sub-callout):
1. Scan unread Gmail (query from config)
2. Extract deadlines (LLM)
3. Propose via Telegram (Approve / Approve+Calendar / Dismiss)
4. On approve → memory + one-shot notify workflows + optional calendar event
5. Fire reminders at lead times

Dashed gold arrows: Task Engine → Agent Runtime (workflow prompt steps)
Dashed gold arrows: Task Engine → Telegram Notifier (proactive messages)

---

### 10. Local Storage — Local-First (bottom-left)

Grey accent. Two columns inside one box:

**App Data** (`~/.best_buddy_agent` or `BEST_BUDDY_AGENT_DATA_DIR`)

| Path | Contents |
|------|----------|
| `memory.db` | Knowledge graph |
| `threads.db` | Conversation history |
| `workflows.db` | Workflow definitions & run state |
| `reminders.db` | Deadline Watch dedupe |
| `memory_vectors/` | FAISS index |
| `vision_cache/` | Cached Telegram photos |
| `gmail/` | OAuth credentials + token |
| `calendar/` | Calendar OAuth token |

**Workspace** (`files_root` in config)

| Path | Contents |
|------|----------|
| Agent workspace | Only tree `read_file` / `write_file` may access |
| Enforced in code + systemd `ReadWritePaths` on server |

**Config** (separate small box, grey)
- `conf/best_buddy_agent.conf`
- `conf/prompts/{en,ru}/` — system prompts, tool descriptions, fragments

---

### 11. Safety & Control Plane (bottom-right)

Reddish-pink accent. Two columns:

**Left — Policies**
- Human approval gates (CLI prompt / Telegram buttons)
- Single-user Telegram allowlist (`TELEGRAM_ALLOWED_USER_ID`)
- Local-first data (no cloud telemetry)
- Gmail: read + drafts only — no send
- `files_root` sandbox for file tools
- Secret redaction in logs (`TELEGRAM_BOT_TOKEN`)
- Startup validation (`best-buddy-agent-doctor`)

**Right — Guardrails**
- `max_tool_iterations` per turn
- Deferred tool flow (`DeferredToolRequests` / `resume_turn`)
- Optional `reliability_required` package check
- systemd filesystem isolation in production
- Tool results treated as untrusted context

---

## Section 3: Footer, Legend, and Flow Summary

### Legend (bottom-right corner)

| Color | Category |
|-------|----------|
| Gold / Yellow | Core orchestration |
| Orange | Tools & execution |
| Purple | Memory & context |
| Grey | Storage & infrastructure |
| Reddish-pink | Safety & governance |

### Arrow key (top-right corner)

| Style | Meaning |
|-------|---------|
| Solid gold arrow | Primary data / control flow |
| Dashed gold arrow | Background / scheduled / async |
| Dotted pink arrow | Untrusted or external input |
| Dashed grey box | External service trust boundary |

### Flow summary (bottom-left, horizontal numbered strip)

1. User input enters via **CLI** or **Telegram** (text, voice→STT, or photo→vision).
2. `runtime.chat_once` hands off to **Agent Runtime**.
3. Runtime assembles **context** + auto-recalled **memories** + language **prompts**.
4. **pydantic-ai Agent** calls **Ollama**; model may emit tool calls.
5. **Tool Router** dispatches to native tools; destructive actions pause for **approval**.
6. Tool results return as **untrusted context**; loop continues until final reply.
7. Response sent to channel (formatted HTML on Telegram); optional updates to **memory**, **workflows**, and **proactive notifications**.

---

## Section 4: One-Paragraph Image AI Prompt (condensed)

*Optional single-block prompt if the tool prefers one paragraph:*

> Dark-mode technical architecture poster titled "Best Buddy Agent Architecture" subtitle "v0.2 pydantic-ai + local Ollama". Central gold hub "Agent Runtime" with context assembly, reasoning loop, tool routing, HITL approval, trace logging. Top-left: CLI and Telegram channels (voice STT, photo vision, proactive notifier). Top-right: Ollama model layer inside dashed external boundary. Left column purple Memory System (SQLite, NetworkX, FAISS, dream cycle) and grey Thread Store. Right column orange Native Tools (filesystem, memory, workflows, Gmail drafts-only, Calendar, web search, revisit_image) via Tool Router. Bottom center Task Engine with workflow scheduler and Deadline Watch Gmail→Telegram flow. Bottom-left grey Local Storage two-column layout (~/.best_buddy_agent + workspace). Bottom-right pink Safety (approval gates, single-user Telegram, sandbox). Gold solid arrows primary flow, dashed gold background jobs, dotted pink untrusted tool results. Legend and 7-step flow summary in footer. Style like Thoth Core Agent Architecture: elegant serif title, sans-serif labels, minimalist line icons, warm gold on charcoal background.
