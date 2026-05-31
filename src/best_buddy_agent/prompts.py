"""Deprecated: prompts live in conf/prompts/{language}/ and are loaded via prompt_loader."""

from __future__ import annotations

from .config import load_config
from .prompt_loader import PROMPT_FILES, TOOL_NAMES, PromptCatalog, load_prompt_catalog

__all__ = [
    "PROMPT_FILES",
    "TOOL_NAMES",
    "PromptCatalog",
    "load_prompt_catalog",
    "load_prompts",
]


def load_prompts() -> PromptCatalog:
    """Return the configured prompt catalog (convenience for scripts)."""
    return load_config().prompts
