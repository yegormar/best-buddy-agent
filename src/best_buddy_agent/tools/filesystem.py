"""Filesystem tools under configured files_root."""

from __future__ import annotations

from pathlib import Path

from ..config import AgentConfig


class ToolError(Exception):
    """Raised when a tool cannot run."""


def _safe_resolve(user_path: str, root: Path) -> Path:
    if not user_path or not user_path.strip():
        raise ToolError("path is required")
    p = Path(user_path.strip())
    if not p.is_absolute():
        p = (root / p).resolve()
    else:
        p = p.resolve()
    try:
        p.relative_to(root)
    except ValueError as exc:
        raise ToolError(f"Path outside allowed files_root: {p}") from exc
    return p


def read_file(config: AgentConfig, path: str, max_chars: int = 30_000) -> str:
    resolved = _safe_resolve(path, config.files_root)
    if not resolved.exists():
        raise ToolError(f"File not found: {resolved}")
    if not resolved.is_file():
        raise ToolError(f"Not a file: {resolved}")
    text = resolved.read_text(encoding="utf-8", errors="replace")
    if len(text) > max_chars:
        return text[:max_chars] + f"\n\n[Truncated: first {max_chars} chars shown]"
    return text


def list_files(config: AgentConfig, pattern: str = "*", max_entries: int = 200) -> str:
    root = config.files_root
    if max_entries < 1 or max_entries > 1000:
        raise ToolError("max_entries must be between 1 and 1000")
    matches = sorted(root.glob(pattern))[:max_entries]
    if not matches:
        return f"No files matching {pattern!r} under {root}"
    lines = []
    for p in matches:
        rel = p.relative_to(root)
        kind = "dir" if p.is_dir() else "file"
        lines.append(f"{kind}: {rel}")
    if len(matches) >= max_entries:
        lines.append(f"[truncated at {max_entries} entries]")
    return "\n".join(lines)


def write_file(config: AgentConfig, path: str, content: str) -> str:
    resolved = _safe_resolve(path, config.files_root)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to {resolved.relative_to(config.files_root)}"
