"""Ensure LLM-facing prompt text is loaded from files, not embedded in Python."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_PKG = ROOT / "src" / "best_buddy_agent"

# Modules that assemble or send LLM instructions/prompts.
_LLM_PROMPT_MODULES = (
    "agent_runtime.py",
    "agent_context.py",
    "llm_runner.py",
    "workflow_engine.py",
    "memory_recall.py",
    "memory_layer.py",
    "memory_extraction.py",
    "dream_cycle.py",
    "memory_import_runner.py",
    "validation.py",
)

_EXEMPT_FILES = {
    SRC_PKG / "prompt_loader.py",
    SRC_PKG / "prompts.py",
}

_FORBIDDEN_SUBSTRINGS = (
    "You are a",
    "You KNOW the following facts",
    "Current date and time:",
    "Workflow context:",
    "Follow the user message precisely",
    "Convert the user intent into a workflow plan",
    "You are checking whether two pieces of information",
    "memory extraction assistant",
    "knowledge-graph curator",
    "self-analysis engine",
    "SCRIPTED MEMORY IMPORT",
    "Read a UTF-8 text file under files_root",
    "Save a durable memory",
    "Intent: {intent}",
)


def _iter_scanned_files() -> list[Path]:
    files: list[Path] = []
    for name in _LLM_PROMPT_MODULES:
        path = SRC_PKG / name
        if path.is_file():
            files.append(path)
    return files


def _string_nodes(tree: ast.AST) -> list[ast.Constant]:
    nodes: list[ast.Constant] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            nodes.append(node)
    return nodes


def test_prompt_registry_files_exist():
    from best_buddy_agent.config import load_config

    cfg = load_config(str(ROOT / "conf" / "best_buddy_agent.conf"))
    assert cfg.prompt_language in ("en", "ru")
    assert cfg.agent_system_prompt.strip()
    assert cfg.prompts.get("background/extraction").strip()
    assert cfg.prompts.get(f"tools/read_file").strip()


def test_no_hardcoded_llm_prompt_literals_in_source():
    violations: list[str] = []
    for path in _iter_scanned_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in _string_nodes(tree):
            value = node.value.strip()
            if len(value) < 40:
                continue
            lowered = value.lower()
            for needle in _FORBIDDEN_SUBSTRINGS:
                if needle.lower() in lowered:
                    violations.append(
                        f"{path.relative_to(ROOT)}:{node.lineno}: contains {needle!r}"
                    )
                    break
    assert not violations, "Hardcoded LLM prompt fragments found:\n" + "\n".join(violations)
