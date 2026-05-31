"""Validation helpers shared by memory extraction/runtime."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def check_contradiction(old_content: str, new_content: str, subject: str) -> str | None:
    """Return a short description of the conflict, or None if compatible.

    Uses an LLM call for semantic understanding.  Falls back to None (allow merge)
    on any exception so extraction is never blocked by an LLM failure.

    Lazy imports avoid circular dependency (validation ← memory_extraction ← agent_runtime).
    """
    if not (old_content or "").strip() or not (new_content or "").strip():
        return None

    try:
        from .config import load_config  # noqa: PLC0415
        from .llm_runner import run_text_completion  # noqa: PLC0415

        cfg = load_config()
        no_keyword = cfg.prompts.get("keywords/contradiction_no")
        prompt = cfg.prompts.format(
            "background/contradiction",
            subject=subject or "this entity",
            old_content=(old_content or "").strip(),
            new_content=(new_content or "").strip(),
        )
        raw = run_text_completion(cfg, prompt).strip()
        if raw.upper() == no_keyword.upper() or raw.upper().startswith(f"{no_keyword.upper()}."):
            return None
        return raw or None
    except Exception:
        logger.debug("check_contradiction LLM call failed, allowing merge", exc_info=True)
        return None
