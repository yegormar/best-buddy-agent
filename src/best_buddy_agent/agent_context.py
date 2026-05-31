"""Context utilities (redaction and backward-compatible memory wrappers)."""

from __future__ import annotations

import re
from typing import Any

from .memory_recall import recall_from_user_messages

_DATA_URI_RE = re.compile(
    r"data:([a-zA-Z0-9][a-zA-Z0-9+.-/]*);base64,[A-Za-z0-9+/=\s]{200,}",
    re.IGNORECASE,
)


def redact_data_uris(text: str) -> str:
    if not text or "base64," not in text:
        return text

    def _sub(match):
        mime = match.group(1)
        approx_bytes = int(len(match.group(0)) * 0.75)
        return f"[inline {mime} stripped, ~{approx_bytes} bytes]"

    return _DATA_URI_RE.sub(_sub, text)


def build_memory_context(user_messages: list[str], top_k: int = 8) -> str:
    block, _meta = build_memory_context_with_meta(user_messages, top_k=top_k)
    return block


def build_memory_context_with_meta(
    user_messages: list[str],
    top_k: int = 8,
    *,
    memory_recall_header: str | None = None,
) -> tuple[str, dict[str, Any]]:
    if memory_recall_header is None:
        from .config import load_config

        memory_recall_header = load_config().prompts.get("fragments/memory_recall_header")
    result = recall_from_user_messages(user_messages, top_k=top_k)
    return result.format_for_system_prompt(memory_recall_header=memory_recall_header), result.meta


__all__ = ["redact_data_uris", "build_memory_context", "build_memory_context_with_meta"]
