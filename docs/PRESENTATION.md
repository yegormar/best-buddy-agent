# Best Buddy — 10-Minute Presentation Script

**[Your Name]** · **[Course]** · **[Date]**  
**5 slides · ~4–5 min live demo · 10 min total**

Assets: `best_buddy_agent_architecture.png` (Slide 3) · `best_buddy_memory_architecture.png` (demo backup)

---

## Run of show

| When | Min | What |
|------|-----|------|
| Slide 1 | 0:45 | Title + sovereignty & extensibility — why I built this |
| Slide 2 | 0:45 | vs OpenClaw & Hermes — why I built my own |
| Slide 3 | 1:15 | Architecture — then go straight to demo |
| **Demo** | **4:30** | Telegram on phone (3 scenarios) |
| Slide 4 | 0:45 | One design trade-off with evidence |
| Slide 5 | 0:45 | What I learned + close |
| Buffer | 0:55 | Questions |

---

## Slide 1 — Title

### On slide

**Best Buddy**  
*Personal AI assistant — sovereign, local, mine*

- **AI sovereignty:** my model, my server, my rules — no provider lock-in
- **No surprise bills:** local **Ollama** — no per-token API fees or usage caps from vendors
- **Built for daily use:** persistent memory, Gmail/calendar, Telegram (text, voice, photos)
- **Built to grow:** modular tools & workflows — easy to add features as I find new areas I need help with

### Say (~50 sec)

> "I'm [name]. Best Buddy is an AI assistant I built for myself as a college student — and plan to use every day.  
> The main reason I didn't just use ChatGPT or Claude is **sovereignty**. Cloud providers can change models, raise prices, throttle you, or cut access overnight — and you pay whatever the meter says. I don't want my daily workflow depending on that.  
> Best Buddy runs on **my hardware** with **local Ollama**: I pick the model, I control the stack, and the cost is fixed — my server, not a subscription that scales with every message.  
> I also designed it to **grow with me**. I don't know every feature I'll need on day one — so the architecture is modular: plug in new tools, wire up workflows, enable integrations in config as I discover gaps. Gmail and Deadline Watch are examples; the next one might be something I haven't thought of yet.  
> Today it **remembers** my courses and deadlines and lives on **Telegram** on my phone. I looked at existing agents first — that's the next slide."

---

## Slide 2 — Why not OpenClaw or Hermes?

### On slide

**Best Buddy vs general-purpose agents**

| | OpenClaw | Hermes | **Best Buddy** |
|---|----------|--------|----------------|
| **Scope** | Huge skill marketplace, many channels | Research-grade platform, many providers & backends | **One stack I own** — only what I use daily |
| **LLM cost** | Often cloud API (BYOK) | OpenRouter, Portal, 200+ models | **Local Ollama only** — fixed cost, no meter |
| **Memory** | Markdown files (`MEMORY.md`) | Skills + session search + Honcho modeling | **Knowledge graph** — typed entities, relations, FAISS recall |
| **Proactive help** | Skills & cron (you configure) | Built-in cron, broad automations | **Deadline Watch** — Gmail scan → approve → remind |
| **Safety** | Sandbox + optional approvals | Command allowlists, many surfaces | **Telegram Approve/Deny** on every risky tool |
| **Codebase** | Large gateway + plugin ecosystem | Full framework (subagents, 6 backends) | **~Single Python package** — pydantic-ai, easy to extend |

**BB wins for me:** sovereignty · structured memory · college workflow baked in · codebase I can actually modify

*OpenClaw & Hermes win on breadth: more channels, more plugins, more out-of-the-box integrations.*

### Say (~45 sec)

> "I evaluated OpenClaw and Hermes — both are impressive open-source agents.  
> OpenClaw gives you thousands of community skills and every chat app; Hermes adds learning loops, subagents, and a dozen model providers.  
> But I didn't need a marketplace — I needed **one system I control end to end**. Cloud-backed agents still tie you to API pricing and provider policy. Markdown memory files are easy to start but hard to query reliably.  
> Best Buddy is narrower on purpose: **local Ollama**, a **real graph** with relations and auto-recall every turn, **Deadline Watch** for my actual email workflow, and a **small codebase** I can extend when I discover the next thing I need.  
> They optimize for coverage; I optimized for **sovereignty and daily reliability**. Architecture next, then live demo."

---

## Slide 3 — Architecture

### On slide

```
Phone (Telegram) ──► Agent runtime ──► Ollama (local LLM)
                         │
            ┌────────────┼────────────┐
            ▼            ▼            ▼
      Knowledge     Gmail /      Workflow
       graph         Calendar      scheduler
     (memory.db)                  (Deadline Watch)
```

- **Threads** = this chat session · **Graph** = facts that persist forever
- Before every reply: **auto-recall** searches the graph and injects what BB already knows
- Risky actions (email drafts, calendar edits, file writes) → **Approve / Deny**

### Visual

`best_buddy_agent_architecture.png` (full slide)

### Say (~75 sec)

> "Telegram is just the UI — the same Python runtime also has a CLI.  
> Every message goes through `run_turn`: recall memories, call the local model, maybe run tools, save new facts.  
> Important idea: **chat is not memory**. Thread history is short-term; the knowledge graph in SQLite plus FAISS is long-term.  
> Deadline Watch is a background workflow: scan unread Gmail, extract due dates, message me on Telegram, and wait for my approval before scheduling reminders.  
> Okay — let me use it like I do on a normal day."

---

## Live demo (~4.5 min)

### Before class

```bash
best-buddy-agent-doctor --config conf/best_buddy_agent.conf --profile telegram
best-buddy-agent-telegram --config conf/best_buddy_agent.conf
```

Check: Ollama up · bot token set · Gmail/Deadline Watch enabled if showing beat 3.

Have ready: phone with Telegram open · laptop with trace log or doctor output as backup.

---

### Beat 1 — Memory survives a new thread (~2 min)

**Do**

1. Text: *"Remember: CS 301 final is April 15. Prof Chen wants questions by email only."*
2. Wait for confirmation.
3. Send `/newthread`
4. Text: *"When is my CS 301 final and how should I contact the prof?"*

**Pass if:** BB answers from memory without you repeating the facts.

**Say before:** "I'm starting a fresh thread — like clearing chat history. My semester facts should still be there."

**Say after:** "That's the knowledge graph. New thread, same long-term memory."

---

### Beat 2 — Voice on the go (~1.5 min)

**Do**

1. Voice note: *"What assignments do I have coming up?"*  
   (or any short question BB can answer from memory / calendar)

**Pass if:** Transcript appears (`echo_transcript`) and reply is grounded, not invented.

**Say before:** "Between classes I send voice notes — local faster-whisper, no cloud STT."

---

### Beat 3 — I stay in control (~1.5 min)

Pick **one** depending on what's reliable in the room:

**Option A — Approval gate**  
Text: *"Draft an email to Prof Chen asking for office hours."*  
**Pass if:** Approve / Deny buttons appear; nothing is sent until you tap.

**Option B — Deadline Watch**  
Show an existing Telegram proposal from a real unread email, or a screenshot from rehearsal.  
**Pass if:** You explain scan → propose → approve → remind at lead times (1d, 0d, 1h).

**Say before:** "BB can act on my behalf, but not silently — I approve drafts and deadline reminders."

---

### If live demo fails

1. Show `best_buddy_memory_architecture.png` — point at recall pipeline (30 sec).
2. Show green `best-buddy-agent-doctor` output or a saved trace log from rehearsal.
3. One line: "Stack is validated offline; live risk is GPU and network in the room."

---

## Slide 4 — Design decision (evidence)

### On slide

**I chose: local + memory-first + human approval**

| Kept | Gave up |
|------|---------|
| Own Ollama host, own data dir | Easy plug-and-play setup |
| Knowledge graph + recall fallbacks | Best-in-class cloud embeddings |
| Telegram + voice + Deadline Watch | Multi-user product features |

Extracted from a large desktop agent (Thoth) → standalone **pydantic-ai** runtime with only what I use daily.

### Say (~60 sec)

> "I didn't want another wrapper around ChatGPT. I trimmed a bigger project down to memory, Telegram, Gmail, calendar, and workflows.  
> I migrated from LangChain to pydantic-ai for a simpler tool loop I can debug.  
> Embeddings are lightweight — semantic search is weaker across languages, so I added keyword and recent-entity fallbacks. That's a real trade-off I tested, not theory.  
> Single-user is fine: I built this for me."

---

## Slide 5 — Learning & close

### On slide

**Built with:** Python · pydantic-ai · SQLite · FAISS · faster-whisper · workflow scheduler

**Learned:** assistants fail without durable memory; building for daily use exposes every bug fast

**Next:** better embeddings · voice replies (TTS) · polish onboarding

**Questions?**

### Say (~60 sec)

> "This project covered agent orchestration, graph storage, speech-to-text, OAuth integrations, and a production Telegram bot with background jobs.  
> Main takeaway: if I can't trust it to remember Tuesday's deadline next month, I won't use it — so memory isn't a feature bolt-on, it's the architecture.  
> I'll keep using BB after this course. Thanks — happy to take questions."

---

## Q&A (not on slides)

| Question | Answer |
|----------|--------|
| Why not ChatGPT? | Forgets context per session; BB stores facts in my graph and recalls them every turn. |
| Why not OpenClaw / Hermes? | Great breadth, but cloud/marketplace complexity; BB is local-only, graph memory, smaller code I own. |
| Why Telegram? | Already on my phone; voice notes; works anywhere without a custom app. |
| Is my data private? | LLM runs on my Ollama host; state lives in `~/.best_buddy_agent`; Gmail/Calendar only if I enable them. |
| Why local Ollama? | Control over model, context size, and no per-token bill; runs on hardware I already have. |
| What if the model hallucinates? | Prompts require `search_memory` before personal facts; destructive tools need approval. |
| Biggest limitation? | Setup cost; single user; embedding quality for mixed-language facts. |

---

## Rubric checklist

| Requirement | Covered in |
|-------------|------------|
| Problem & audience | Slide 1 — daily use, AI sovereignty, extensible as needs grow |
| Why this project | Slide 2 — vs OpenClaw/Hermes; Slide 4 — design trade-offs |
| Concepts / application | Slide 3 — graph, recall, tools, workflows |
| Learning evidence | Slide 5 + demo |
| Live demo | Beats 1–3 (~4.5 min) |
| Reflection | Slide 5 — memory-first lesson, continued use |

---

## Rehearsal checklist

- [ ] Doctor passes with `--profile telegram`
- [ ] Beat 1 works end-to-end including `/newthread`
- [ ] Voice note transcribes in under ~10 sec on your GPU
- [ ] Approval buttons or Deadline Watch screenshot ready for beat 3
- [ ] Slides exported; comparison table on Slide 2; architecture PNG on Slide 3
- [ ] Phone on Do Not Disturb except Telegram
