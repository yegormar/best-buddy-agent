"""Load LLM prompts from language-specific files under conf/prompts/."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

# Registry of prompt keys → relative path under conf/prompts/{language}/.
PROMPT_FILES: dict[str, str] = {
    "agent_system": "agent_system.txt",
    "import_turn": "import_turn.txt",
    "fragments/assistant_identity": "fragments/assistant_identity.txt",
    "fragments/datetime": "fragments/datetime.txt",
    "fragments/memory_recall_header": "fragments/memory_recall_header.txt",
    "fragments/workflow_context_header": "fragments/workflow_context_header.txt",
    "fragments/gmail_available": "fragments/gmail_available.txt",
    "fragments/web_available": "fragments/web_available.txt",
    "fragments/calendar_available": "fragments/calendar_available.txt",
    "fragments/deadline_watch": "fragments/deadline_watch.txt",
    "background/extraction": "background/extraction.txt",
    "background/contradiction": "background/contradiction.txt",
    "dream/merge": "dream/merge.txt",
    "dream/enrich": "dream/enrich.txt",
    "dream/infer": "dream/infer.txt",
    "dream/insights": "dream/insights.txt",
    "planner/workflow_nl_system": "planner/workflow_nl_system.txt",
    "planner/workflow_nl_user": "planner/workflow_nl_user.txt",
    "llm/text_completion_system": "llm/text_completion_system.txt",
    "keywords/contradiction_no": "keywords/contradiction_no.txt",
}

TOOL_NAMES: tuple[str, ...] = (
    "read_file",
    "list_files",
    "write_file",
    "search_memory",
    "save_memory",
    "list_memories",
    "get_memory",
    "delete_memory",
    "link_memories",
    "update_memory",
    "explore_connections",
    "workflow_run_status",
    "trigger_workflow",
    "list_workflows",
    "create_workflow",
    "update_workflow",
    "delete_workflow",
    "run_workflow_now",
    "create_reminder",
    "search_gmail",
    "get_gmail_message",
    "get_gmail_thread",
    "create_gmail_draft",
    "get_current_datetime",
    "search_events",
    "create_calendar_event",
    "update_calendar_event",
    "web_search",
    "fetch_url",
)


class PromptError(Exception):
    """Raised when a prompt file is missing or invalid."""


@dataclass(slots=True)
class PromptCatalog:
    """Language-specific prompt bundle loaded from conf/prompts/{language}/."""

    language: str
    root: Path
    agent_system_override: Path | None = None
    _cache: dict[str, str] = field(default_factory=dict, repr=False)

    def path_for(self, key: str) -> Path:
        if key == "agent_system" and self.agent_system_override is not None:
            return self.agent_system_override
        if key.startswith("tools/"):
            tool = key.removeprefix("tools/")
            if tool not in TOOL_NAMES:
                raise PromptError(f"Unknown tool prompt key: {key}")
            return self.root / "tools" / f"{tool}.txt"
        rel = PROMPT_FILES.get(key)
        if rel is None:
            raise PromptError(f"Unknown prompt key: {key}")
        return self.root / rel

    def get(self, key: str) -> str:
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        path = self.path_for(key)
        if not path.is_file():
            raise PromptError(f"Prompt file not found for {key!r}: {path}")
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            raise PromptError(f"Prompt file is empty for {key!r}: {path}")
        self._cache[key] = text
        return text

    def format(self, key: str, **kwargs: object) -> str:
        return self.get(key).format(**kwargs)

    def tool_catalog(self) -> list[tuple[str, str]]:
        return [(name, self.get(f"tools/{name}")) for name in TOOL_NAMES]

    def fingerprint(self) -> str:
        parts: list[str] = [self.language]
        keys = sorted(PROMPT_FILES) + [f"tools/{n}" for n in TOOL_NAMES]
        for key in keys:
            path = self.path_for(key)
            if path.is_file():
                parts.append(path.read_text(encoding="utf-8"))
        return hashlib.sha256("\n---\n".join(parts).encode()).hexdigest()


def load_prompt_catalog(
    *,
    conf_dir: Path,
    language: str,
    agent_system_override: Path | None = None,
) -> PromptCatalog:
    lang = (language or "en").strip()
    if not lang:
        raise PromptError("prompt language must be non-empty")
    root = (conf_dir / "prompts" / lang).resolve()
    if not root.is_dir():
        raise PromptError(f"Prompt language directory not found: {root}")
    catalog = PromptCatalog(language=lang, root=root, agent_system_override=agent_system_override)
    # Fail fast on missing required prompts.
    for key in PROMPT_FILES:
        catalog.get(key)
    for name in TOOL_NAMES:
        catalog.get(f"tools/{name}")
    return catalog
