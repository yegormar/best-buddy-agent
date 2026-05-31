"""Single memory recall path for instruction injection and search_memory tool.

Pipeline matches Thoth ``agent.py`` auto-recall (``graph_enhanced_recall``) plus the
pre-migration ``agent_context.build_memory_context`` fallback when semantic/keyword
miss — see ``docs/THOTH_EXTRACTION_MAP.md`` and ``agent_flow_analysis.md``.

Best Buddy agent uses ``LocalHashEmbedding`` (``documents.py``), not Thoth's
``Qwen/Qwen3-Embedding-0.6B``. Cross-language queries often miss FAISS; the
``list_entities`` step is the bounded safety net so profile facts still inject.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .knowledge_graph import graph_enhanced_recall, list_entities, search_entities


def _merge_memories(primary: list[dict], extra: list[dict]) -> list[dict]:
    seen = {m["id"] for m in primary if m.get("id")}
    merged = list(primary)
    for m in extra:
        mid = m.get("id")
        if mid and mid not in seen:
            merged.append(m)
            seen.add(mid)
    return merged


def format_memory_lines(memories: list[dict]) -> list[str]:
    lines = []
    for m in memories:
        category = m.get("category", m.get("entity_type", ""))
        content = m.get("content", m.get("description", ""))
        line = f"- [id={m['id']}] [{category}] {m['subject']}: {content}"
        if m.get("via") == "graph" and m.get("relations"):
            rels = "; ".join(f"{r['from']} → {r['type']} → {r['to']}" for r in m["relations"])
            line += f" (connected via: {rels})"
        lines.append(line)
    return lines


@dataclass(frozen=True, slots=True)
class MemoryRecallResult:
    """Outcome of one recall operation (shared by inject + tool)."""

    query: str
    memories: list[dict]
    meta: dict[str, Any]

    @property
    def recall_path(self) -> str:
        return str(self.meta.get("recall_path", "none"))

    def format_for_system_prompt(self, *, memory_recall_header: str) -> str:
        if not self.memories:
            return ""
        lines = format_memory_lines(self.memories)
        return memory_recall_header + "\n" + "\n".join(lines)

    def format_for_tool(self) -> str:
        if not self.memories:
            return "No matching memories."
        return "\n".join(format_memory_lines(self.memories))


def recall_memories(query: str, *, top_k: int = 8) -> MemoryRecallResult:
    """Recall: graph_enhanced_recall → keyword SQL → recent entities if still empty."""
    q = (query or "").strip()[:2000]
    meta: dict[str, Any] = {
        "recall_query": q,
        "recall_path": "none",
        "injected_subjects": [],
    }
    if not q:
        return MemoryRecallResult(query=q, memories=[], meta=meta)

    memories = graph_enhanced_recall(q, top_k=top_k, threshold=0.35, hops=1)
    if memories:
        meta["recall_path"] = "semantic"
    else:
        memories = search_entities(q, limit=top_k)
        if memories:
            meta["recall_path"] = "keyword"
        else:
            memories = list_entities(limit=top_k)
            if memories:
                meta["recall_path"] = "list_recent"

    if memories:
        meta["injected_subjects"] = [m.get("subject", "") for m in memories]

    return MemoryRecallResult(query=q, memories=memories, meta=meta)


def recall_from_user_messages(
    user_messages: list[str],
    *,
    top_k: int = 8,
) -> MemoryRecallResult:
    """Build recall query from recent user lines (instruction injection)."""
    query = " ".join((m or "").strip() for m in user_messages if (m or "").strip())
    return recall_memories(query, top_k=top_k)
