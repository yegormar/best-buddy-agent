"""Knowledge-graph memory tools."""

from __future__ import annotations

import json
import time

from .. import knowledge_graph as kg
from ..knowledge_graph import (
    DOCUMENT_MULTI_SOURCE,
    VALID_ENTITY_TYPES,
    format_valid_entity_types,
    normalize_entity_type,
)
from ..memory import delete_memory as _delete_memory
from ..memory import get_memory
from ..memory import list_memories as _list_memories
from ..memory import save_memory as _save_memory
from ..memory import update_memory as _update_memory
from ..memory_recall import recall_memories

_VALID_TYPES_HINT = format_valid_entity_types()

# Storyteller labels in oral-history payloads → canonical User entity (link resolution).
_NARRATOR_SUBJECTS = frozenset({
    "narrator",
    "storyteller",
    "speaker",
    "the_narrator",
    "рассказчик",
    "рассказчица",
})

# Relation types too vague for link_memories (characterization / contrast, not edges).
_VAGUE_RELATION_TYPES = frozenset({
    "related_to",
    "associated_with",
    "connected_to",
    "linked_to",
    "has_relation",
    "involves",
    "correlates_with",
    "describes",
    "described_as",
    "characterizes",
    "characterized_as",
    "differs_from",
    "different_from",
    "contrasts_with",
    "unlike",
    "compared_to",
    "in_contrast_to",
    "same_person",
    "same_as",
    "alias_of",
    "also_known_as",
})


class ToolError(Exception):
    """Raised when a memory tool fails."""


def _resolve_category(category: str) -> str:
    """Normalize category; raise ToolError with guidance if still invalid."""
    normalized = normalize_entity_type(category)
    if normalized in VALID_ENTITY_TYPES:
        return normalized
    raise ToolError(
        f"Invalid category '{category}'. Use one of: {_VALID_TYPES_HINT}. "
        "Hints: person (people), preference (likes/dislikes), fact (general life details), "
        "event (dates/milestones), place, skill."
    )


def _resolve_entity(name_or_id: str) -> dict | None:
    """Resolve an entity by subject name (preferred) or hex ID."""
    raw = (name_or_id or "").strip()
    if not raw:
        return None
    norm = kg._normalize_subject(raw)
    if norm in _NARRATOR_SUBJECTS:
        user = kg.find_by_subject(None, "User")
        if user:
            return user
    entity = kg.find_by_subject(entity_type=None, subject=raw)
    if entity:
        return entity
    return kg.get_entity(raw)


def search_memory(query: str, top_k: int = 8) -> str:
    top_k = max(1, min(top_k, 20))
    if not query.strip():
        # Small models often call search_memory with query="" for broad questions;
        # list everything instead of failing the turn.
        return list_memories(limit=top_k)
    return recall_memories(query.strip(), top_k=top_k).format_for_tool()


def save_memory_entry(
    category: str,
    subject: str,
    content: str,
    tags: str = "",
    source: str = "live",
) -> str:
    if not subject.strip():
        raise ToolError("subject is required")
    if not content.strip():
        raise ToolError("content is required")
    try:
        cat = _resolve_category(category)
        res = _save_memory(
            cat, subject.strip(), content.strip(), tags=tags, source=source
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return json.dumps(res, ensure_ascii=False)


def list_memories(category: str | None = None, limit: int = 30) -> str:
    raw = (category or "").strip()
    filter_type: str | None = None
    if raw:
        normalized = normalize_entity_type(raw)
        if normalized not in VALID_ENTITY_TYPES:
            return (
                f"Unknown category '{raw}'. Valid types: {_VALID_TYPES_HINT}. "
                "Omit category (empty string) to list all stored memories."
            )
        filter_type = normalized

    rows = _list_memories(category=filter_type, limit=limit)
    if not rows:
        if filter_type:
            return (
                f"No memories in category '{filter_type}'. "
                "Omit category to list all memories."
            )
        return "No memories stored."
    lines = []
    for r in rows:
        lines.append(
            f"- [id={r['id']}] [{r.get('category', '')}] {r.get('subject', '')}: "
            f"{(r.get('content') or '')[:200]}"
        )
    return "\n".join(lines)


def get_memory_by_id(memory_id: str) -> str:
    row = get_memory(memory_id)
    if not row:
        raise ToolError(f"Unknown memory id: {memory_id}")
    return json.dumps(row, ensure_ascii=False, indent=2)


def delete_memory_by_id(memory_id: str) -> str:
    if not _delete_memory(memory_id):
        raise ToolError(f"Unknown memory id: {memory_id}")
    return json.dumps({"deleted": memory_id}, ensure_ascii=False)


def link_memories_entities(
    source_id: str,
    target_id: str,
    relation_type: str,
    *,
    source: str = "live",
) -> str:
    """Create a directed relation between two entities resolved by name or ID.

    Retries once after 0.5 s to handle the case where a parallel save_memory
    call in the same agent turn hasn't committed yet.
    """
    if not source_id.strip():
        raise ToolError("source_id is required")
    if not target_id.strip():
        raise ToolError("target_id is required")
    if not relation_type.strip():
        raise ToolError("relation_type is required")

    source_entity = _resolve_entity(source_id.strip())
    if not source_entity:
        time.sleep(0.5)
        source_entity = _resolve_entity(source_id.strip())
    if not source_entity:
        return (
            f"Link skipped: source entity '{source_id}' not found. "
            "Call save_memory for it first, then retry link_memories."
        )

    target_entity = _resolve_entity(target_id.strip())
    if not target_entity:
        time.sleep(0.5)
        target_entity = _resolve_entity(target_id.strip())
    if not target_entity:
        return (
            f"Link skipped: target entity '{target_id}' not found. "
            "Call save_memory for it first, then retry link_memories."
        )

    norm_type = kg.normalize_relation_type(relation_type.strip())
    if not kg.is_allowed_relation_type(relation_type.strip()):
        return (
            f"Link skipped: relation type '{relation_type}' "
            f"(normalized: {norm_type!r}) is not in the allowed vocabulary. "
            "Use a specific type from the import prompt reference, or omit the link."
        )
    if source_entity["id"] == target_entity["id"]:
        return "Link skipped: cannot link an entity to itself."

    rel = kg.add_relation(
        source_entity["id"],
        target_entity["id"],
        norm_type,
        source=source,
    )
    if rel is None:
        return (
            f"Relation already exists: "
            f"{source_entity['subject']} --[{norm_type}]--> {target_entity['subject']}"
        )

    return (
        f"Relationship created.\n"
        f"{source_entity['subject']} --[{rel['relation_type']}]--> {target_entity['subject']}\n"
        f"Relation ID: {rel['id']}"
    )


def update_memory_entry(
    memory_id: str,
    content: str,
    subject: str = "",
    aliases: str = "",
    tags: str = "",
    category: str = "",
) -> str:
    """Update an existing memory's content and optional metadata fields."""
    if not memory_id.strip():
        raise ToolError("memory_id is required")
    if not content.strip():
        raise ToolError("content is required")

    kwargs: dict = {}
    if subject.strip():
        kwargs["subject"] = subject.strip()
    if aliases.strip():
        kwargs["aliases"] = aliases.strip()
    if tags.strip():
        kwargs["tags"] = tags.strip()
    if category.strip():
        try:
            kwargs["category"] = _resolve_category(category.strip())
        except ToolError:
            pass  # keep existing category if provided value is invalid

    result = _update_memory(memory_id.strip(), content.strip(), **kwargs)
    if result is None:
        raise ToolError(
            f"Memory '{memory_id}' not found. "
            "Use search_memory or list_memories to find the correct ID."
        )
    return json.dumps(result, ensure_ascii=False, indent=2)


def explore_connections_for_entity(entity_id: str, hops: int = 1) -> str:
    """Explore the knowledge graph around an entity by name or ID."""
    if not entity_id.strip():
        raise ToolError("entity_id is required")

    entity = _resolve_entity(entity_id.strip())
    if not entity:
        raise ToolError(
            f"Entity '{entity_id}' not found. "
            "Use search_memory or list_memories to find the correct name or ID."
        )

    hops = max(1, min(hops, 3))
    resolved_id = entity["id"]

    relations = kg.get_relations(resolved_id)
    neighbors = kg.get_neighbors(resolved_id, hops=hops)

    lines: list[str] = [
        f"{entity.get('subject', '?')} ({entity.get('entity_type', '?')})"
    ]

    if relations:
        lines.append(f"\nRelationships ({len(relations)}):")
        for rel in relations:
            arrow = "-->" if rel["direction"] == "outgoing" else "<--"
            lines.append(
                f"  {arrow} [{rel['relation_type']}] {rel['peer_subject']} "
                f"(id: {rel['peer_id']})"
            )
    else:
        lines.append("\nNo direct relationships yet. Use link_memories to create some.")

    if neighbors and len(neighbors) > len(relations):
        lines.append(f"\nNearby entities within {hops} hop(s): {len(neighbors)}")
        for n in neighbors[:15]:
            hop = n.get("hop", "?")
            lines.append(
                f"  [{hop} hop] {n.get('subject', '?')} ({n.get('entity_type', '?')}) "
                f"(id: {n['id']})"
            )
        if len(neighbors) > 15:
            lines.append(f"  ... and {len(neighbors) - 15} more")

    mermaid = kg.to_mermaid(resolved_id, hops=hops, max_nodes=15)
    if mermaid and mermaid.count("\n") > 1:
        lines.append(f"\n```mermaid\n{mermaid}\n```")

    return "\n".join(lines)
