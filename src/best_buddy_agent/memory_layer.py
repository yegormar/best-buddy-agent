"""Memory recall layer — delegates to memory_recall."""

from __future__ import annotations

from typing import Any

from .memory_recall import recall_from_user_messages


def recall_context_for_turn(
    user_messages: list[str],
    user_text: str,
    top_k: int = 8,
    *,
    memory_recall_header: str,
) -> str:
    parts = list(user_messages)
    if user_text.strip() and (not parts or parts[-1].strip() != user_text.strip()):
        parts.append(user_text)
    return recall_from_user_messages(parts, top_k=top_k).format_for_system_prompt(
        memory_recall_header=memory_recall_header
    )


def recall_context_for_turn_with_meta(
    user_messages: list[str],
    user_text: str,
    top_k: int = 8,
    *,
    memory_recall_header: str,
) -> tuple[str, dict[str, Any]]:
    parts = list(user_messages)
    if user_text.strip() and (not parts or parts[-1].strip() != user_text.strip()):
        parts.append(user_text)
    result = recall_from_user_messages(parts, top_k=top_k)
    return result.format_for_system_prompt(memory_recall_header=memory_recall_header), result.meta
