"""Run scripted agent turns to import interview facts into the knowledge graph."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from pydantic_ai.messages import ModelMessage

from . import agent_runtime
from .agent_runtime import InterruptResult, TurnResult, run_turn
from .config import AgentConfig
from . import knowledge_graph as kg
from .knowledge_graph import DOCUMENT_MULTI_SOURCE, count_relations
from .memory import count_memories, get_memory
from .tools import memory_tools as mem_tools


@dataclass(slots=True)
class SaveMemoryRecord:
    category: str
    subject: str
    tags: str
    memory_id: str | None = None
    error: str | None = None
    verified_in_db: bool = False
    tags_include_conversation: bool = False


@dataclass(slots=True)
class LinkMemoryRecord:
    source_id: str
    target_id: str
    relation_type: str
    error: str | None = None
    verified_created: bool = False


@dataclass(slots=True)
class FactsImportResult:
    conversation_id: str
    facts_path: str
    status: str
    agent_reply: str
    entity_count_before: int
    entity_count_after: int
    save_memory_attempts: int
    save_memory_ok: int
    link_memory_attempts: int = 0
    link_memory_ok: int = 0
    relation_count_before: int = 0
    relation_count_after: int = 0
    saves: list[SaveMemoryRecord] = field(default_factory=list)
    links: list[LinkMemoryRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "facts_path": self.facts_path,
            "status": self.status,
            "agent_reply": self.agent_reply,
            "entity_count_before": self.entity_count_before,
            "entity_count_after": self.entity_count_after,
            "save_memory_attempts": self.save_memory_attempts,
            "save_memory_ok": self.save_memory_ok,
            "link_memory_attempts": self.link_memory_attempts,
            "link_memory_ok": self.link_memory_ok,
            "relation_count_before": self.relation_count_before,
            "relation_count_after": self.relation_count_after,
            "saves": [
                {
                    "category": s.category,
                    "subject": s.subject,
                    "tags": s.tags,
                    "memory_id": s.memory_id,
                    "error": s.error,
                    "verified_in_db": s.verified_in_db,
                    "tags_include_conversation": s.tags_include_conversation,
                }
                for s in self.saves
            ],
            "links": [
                {
                    "source_id": lk.source_id,
                    "target_id": lk.target_id,
                    "relation_type": lk.relation_type,
                    "error": lk.error,
                    "verified_created": lk.verified_created,
                }
                for lk in self.links
            ],
            "errors": self.errors,
        }


def default_import_prompt_path(config: AgentConfig | None = None) -> Path:
    if config is not None:
        return config.prompts.path_for("import_turn")
    from .config import load_config

    return load_config().prompts.path_for("import_turn")


def build_import_user_message(
    *,
    conversation_id: str,
    facts_text: str,
    prompt_template_path: Path | None = None,
    prompts_config: AgentConfig | None = None,
) -> str:
    if prompt_template_path is not None:
        template = prompt_template_path.read_text(encoding="utf-8")
    else:
        cfg = prompts_config
        if cfg is None:
            from .config import load_config

            cfg = load_config()
        template = cfg.prompts.get("import_turn")
    return template.format(conversation_id=conversation_id, facts_text=facts_text.strip())


def conversation_id_from_facts_path(path: Path) -> str:
    return path.stem.replace("_facts", "")


class FactsPathError(ValueError):
    """Raised when an import path does not match the expected uploads layout."""


@dataclass(slots=True)
class FactsImportScope:
    """Resolved import target(s) inferred from a filesystem path."""

    input_path: Path
    facts_files: list[Path]
    user_id: str | None = None
    conversations_dir: Path | None = None

    @property
    def conversation_ids(self) -> list[str]:
        return [conversation_id_from_facts_path(p) for p in self.facts_files]


CHECKPOINT_FILENAME = "facts_import_checkpoint.json"
_CHECKPOINT_SKIP_STATUSES = frozenset({"ok"})


def facts_import_checkpoint_path(data_dir: Path) -> Path:
    return data_dir.expanduser().resolve() / CHECKPOINT_FILENAME


def load_facts_import_checkpoint(data_dir: Path) -> dict[str, dict[str, Any]]:
    """Return map of absolute facts file path → checkpoint entry."""
    path = facts_import_checkpoint_path(data_dir)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    files = payload.get("files")
    return dict(files) if isinstance(files, dict) else {}


def save_facts_import_checkpoint(data_dir: Path, files: dict[str, dict[str, Any]]) -> None:
    path = facts_import_checkpoint_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"files": files}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def partition_facts_files_by_checkpoint(
    facts_files: list[Path],
    checkpoint: dict[str, dict[str, Any]],
    *,
    force: bool = False,
) -> tuple[list[Path], list[Path]]:
    """Return (pending, skipped) absolute-path lists."""
    if force:
        return list(facts_files), []
    pending: list[Path] = []
    skipped: list[Path] = []
    for facts_path in facts_files:
        key = str(facts_path.expanduser().resolve())
        entry = checkpoint.get(key)
        if entry and str(entry.get("status") or "") in _CHECKPOINT_SKIP_STATUSES:
            skipped.append(facts_path)
        else:
            pending.append(facts_path)
    return pending, skipped


def record_facts_import_checkpoint(
    data_dir: Path,
    facts_path: Path,
    result: FactsImportResult,
    *,
    started_at: str | None = None,
    finished_at: str | None = None,
    duration_seconds: float | None = None,
) -> None:
    checkpoint = load_facts_import_checkpoint(data_dir)
    key = str(facts_path.expanduser().resolve())
    entry: dict[str, Any] = {
        "conversation_id": result.conversation_id,
        "status": result.status,
        "updated_at": datetime.now().isoformat(),
        "save_memory_ok": result.save_memory_ok,
        "link_memory_ok": result.link_memory_ok,
        "errors": result.errors,
    }
    if started_at is not None:
        entry["started_at"] = started_at
    if finished_at is not None:
        entry["finished_at"] = finished_at
    if duration_seconds is not None:
        entry["duration_seconds"] = duration_seconds
    checkpoint[key] = entry
    save_facts_import_checkpoint(data_dir, checkpoint)


def user_id_from_uploads_path(path: Path) -> str | None:
    """Return user id from .../uploads/users/<user-id>/... when present."""
    parts = path.resolve().parts
    for idx, part in enumerate(parts):
        if part == "users" and idx + 1 < len(parts):
            return parts[idx + 1]
    return None


def _nested_facts_file(conv_dir: Path) -> Path | None:
    """.../conversations/<conv-id>/<conv-id>_facts.txt"""
    if not conv_dir.is_dir():
        return None
    candidate = conv_dir / f"{conv_dir.name}_facts.txt"
    return candidate if candidate.is_file() else None


def _collect_facts_files_in_conversations(conversations_dir: Path) -> list[Path]:
    """Collect facts files under a conversations directory (nested or flat layout)."""
    if not conversations_dir.is_dir():
        return []
    found: list[Path] = []
    for item in sorted(conversations_dir.iterdir()):
        if item.is_file() and item.name.endswith("_facts.txt"):
            found.append(item)
            continue
        nested = _nested_facts_file(item)
        if nested is not None:
            found.append(nested)
    return found


def resolve_facts_import_paths(input_path: Path) -> FactsImportScope:
    """Infer user id and fact file(s) from an uploads path.

    Accepted inputs (must exist):
    - A *_facts.txt file (nested or flat under conversations/)
    - A conversation directory containing <conv-id>_facts.txt
    - A conversations/ directory (imports all matching fact files)
    - A user directory containing conversations/ (imports all)
    """
    path = input_path.expanduser().resolve()
    if not path.exists():
        raise FactsPathError(f"Path does not exist: {path}")

    _LAYOUT_HELP = (
        "Expected layout under uploads:\n"
        "  .../uploads/users/<user-id>/conversations/<conv-id>/<conv-id>_facts.txt\n"
        "  .../uploads/users/<user-id>/conversations/<conv-id>_facts.txt"
    )

    user_id = user_id_from_uploads_path(path)

    if path.is_file():
        if not path.name.endswith("_facts.txt"):
            raise FactsPathError(
                f"Not a facts file: {path.name!r}. Pass *_facts.txt or a directory.\n{_LAYOUT_HELP}"
            )
        return FactsImportScope(
            input_path=path,
            facts_files=[path],
            user_id=user_id,
            conversations_dir=path.parent if path.parent.name == "conversations" else None,
        )

    if not path.is_dir():
        raise FactsPathError(f"Not a file or directory: {path}\n{_LAYOUT_HELP}")

    # .../users/<user-id> (contains conversations/)
    conversations_dir = path / "conversations" if (path / "conversations").is_dir() else None
    if conversations_dir is not None and path.name != "conversations":
        files = _collect_facts_files_in_conversations(conversations_dir)
        if not files:
            raise FactsPathError(
                f"No *_facts.txt files found under {conversations_dir}\n{_LAYOUT_HELP}"
            )
        return FactsImportScope(
            input_path=path,
            facts_files=files,
            user_id=user_id or user_id_from_uploads_path(conversations_dir),
            conversations_dir=conversations_dir,
        )

    # .../conversations
    if path.name == "conversations":
        files = _collect_facts_files_in_conversations(path)
        if not files:
            raise FactsPathError(
                f"No *_facts.txt files found under {path}\n{_LAYOUT_HELP}"
            )
        return FactsImportScope(
            input_path=path,
            facts_files=files,
            user_id=user_id,
            conversations_dir=path,
        )

    # .../conversations/<conv-id>
    single = _nested_facts_file(path)
    if single is not None:
        conv_dir = path.parent if path.parent.name == "conversations" else None
        return FactsImportScope(
            input_path=path,
            facts_files=[single],
            user_id=user_id,
            conversations_dir=conv_dir,
        )

    # Directory that might contain conversation subdirs (non-standard parent name)
    files = _collect_facts_files_in_conversations(path)
    if files:
        return FactsImportScope(
            input_path=path,
            facts_files=files,
            user_id=user_id,
            conversations_dir=path,
        )

    raise FactsPathError(
        f"Could not find any *_facts.txt files under {path}\n{_LAYOUT_HELP}"
    )


def discover_facts_files(conversations_dir: Path, conversation_id: str | None = None) -> list[Path]:
    """Legacy helper: list fact files under a conversations directory."""
    if conversation_id:
        candidate = conversations_dir / conversation_id / f"{conversation_id}_facts.txt"
        if candidate.is_file():
            return [candidate]
        flat = conversations_dir / f"{conversation_id}_facts.txt"
        return [flat] if flat.is_file() else []
    return _collect_facts_files_in_conversations(conversations_dir)


@contextmanager
def capture_save_memory_calls():
    """Record save_memory and link_memories invocations during an agent turn."""
    saves: list[SaveMemoryRecord] = []
    links: list[LinkMemoryRecord] = []
    original = agent_runtime._trace_tool_invoke

    def wrapped(config: AgentConfig, name: str, args: dict[str, Any], fn: Callable[[], str]) -> str:
        if name == "save_memory":
            record = SaveMemoryRecord(
                category=str(args.get("category") or ""),
                subject=str(args.get("subject") or ""),
                tags=str(args.get("tags") or ""),
            )
            saves.append(record)
            try:
                raw = fn()
            except Exception as exc:
                record.error = str(exc)
                raise
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                record.error = f"save_memory returned non-JSON: {raw[:200]}"
                raise mem_tools.ToolError(record.error) from exc
            record.memory_id = str(payload.get("id") or "") or None
            return raw

        if name == "link_memories":
            lk = LinkMemoryRecord(
                source_id=str(args.get("source_id") or ""),
                target_id=str(args.get("target_id") or ""),
                relation_type=str(args.get("relation_type") or ""),
            )
            links.append(lk)
            try:
                raw = fn()
            except mem_tools.ToolError as exc:
                lk.error = str(exc)
                raise
            except Exception as exc:
                lk.error = str(exc)
                raise
            if raw.startswith("Link skipped:"):
                lk.error = raw
            lk.verified_created = raw.startswith("Relationship created")
            return raw

        return original(config, name, args, fn)

    agent_runtime._trace_tool_invoke = wrapped
    try:
        yield saves, links
    finally:
        agent_runtime._trace_tool_invoke = original


def verify_save_records(
    records: list[SaveMemoryRecord],
    *,
    conversation_id: str,
    require_conversation_tag: bool = True,
    expected_source: str | None = None,
) -> list[str]:
    """Return verification error strings (empty list means all OK)."""
    errors: list[str] = []
    tag_needle = f"conversation:{conversation_id}"
    for idx, record in enumerate(records, start=1):
        if record.error:
            errors.append(f"save #{idx} failed: {record.error}")
            continue
        if not record.memory_id:
            errors.append(f"save #{idx} missing id in tool result")
            continue
        row = get_memory(record.memory_id)
        record.verified_in_db = row is not None
        if not record.verified_in_db:
            errors.append(f"save #{idx} id={record.memory_id} not found via get_memory")
            continue
        if expected_source is not None:
            actual_source = str(row.get("source") or "")
            subject_norm = kg._normalize_subject(str(row.get("subject") or ""))
            allowed_sources = {expected_source, DOCUMENT_MULTI_SOURCE}
            if subject_norm == "user":
                if actual_source not in allowed_sources:
                    errors.append(
                        f"save #{idx} id={record.memory_id} source={actual_source!r}, "
                        f"expected one of {sorted(allowed_sources)!r}"
                    )
            elif actual_source != expected_source:
                errors.append(
                    f"save #{idx} id={record.memory_id} source={actual_source!r}, "
                    f"expected {expected_source!r}"
                )
        if require_conversation_tag:
            tags = str(row.get("tags") or "")
            record.tags_include_conversation = tag_needle in tags
            if not record.tags_include_conversation:
                errors.append(
                    f"save #{idx} id={record.memory_id} missing tag {tag_needle!r} (tags={tags!r})"
                )
    return errors


def _facts_import_status(
    *,
    ok_count: int,
    min_successful_saves: int,
    save_verify_failures: int,
    link_hard_failures: int,
    link_skip_count: int,
    strict_links: bool,
) -> str:
    """``ok`` when saves verify; link issues fail only in ``strict_links`` mode."""
    if ok_count < min_successful_saves or save_verify_failures:
        return "failed"
    if strict_links and (link_hard_failures or link_skip_count):
        return "failed"
    return "ok"


def import_facts_file_via_agent(
    *,
    config: AgentConfig,
    facts_path: Path,
    thread_id: str = "memory-import",
    min_successful_saves: int = 1,
    require_conversation_tag: bool = True,
    strict_links: bool = False,
    prompt_template_path: Path | None = None,
    agent=None,
) -> FactsImportResult:
    conversation_id = conversation_id_from_facts_path(facts_path)
    facts_text = facts_path.read_text(encoding="utf-8")
    user_message = build_import_user_message(
        conversation_id=conversation_id,
        facts_text=facts_text,
        prompt_template_path=prompt_template_path,
        prompts_config=config,
    )
    memory_source = f"document:{conversation_id}"

    before = count_memories()
    rel_before = count_relations()
    turn_out: TurnResult | InterruptResult | None = None
    run_error: str | None = None
    saves: list[SaveMemoryRecord] = []
    links: list[LinkMemoryRecord] = []
    try:
        with capture_save_memory_calls() as (saves, links):
            turn_out = run_turn(
                config,
                thread_id,
                user_message,
                message_history=[],
                persist_thread=False,
                _agent=agent,
                memory_source=memory_source,
            )
    except Exception as exc:
        run_error = str(exc)

    after = count_memories()
    rel_after = count_relations()
    if run_error:
        return FactsImportResult(
            conversation_id=conversation_id,
            facts_path=str(facts_path),
            status="failed",
            agent_reply=f"error:{run_error[:200]}",
            entity_count_before=before,
            entity_count_after=after,
            save_memory_attempts=len(saves),
            save_memory_ok=sum(1 for s in saves if s.error is None and s.memory_id),
            link_memory_attempts=len(links),
            link_memory_ok=sum(1 for lk in links if lk.error is None and lk.verified_created),
            relation_count_before=rel_before,
            relation_count_after=rel_after,
            saves=saves,
            links=links,
            errors=[run_error],
        )

    if turn_out is None:
        return FactsImportResult(
            conversation_id=conversation_id,
            facts_path=str(facts_path),
            status="failed",
            agent_reply="error:no turn result",
            entity_count_before=before,
            entity_count_after=after,
            save_memory_attempts=len(saves),
            save_memory_ok=0,
            link_memory_attempts=len(links),
            link_memory_ok=0,
            relation_count_before=rel_before,
            relation_count_after=rel_after,
            saves=saves,
            links=links,
            errors=["agent turn produced no result"],
        )

    if isinstance(turn_out, InterruptResult):
        return FactsImportResult(
            conversation_id=conversation_id,
            facts_path=str(facts_path),
            status="failed",
            agent_reply=f"interrupt:{turn_out.tool_name}",
            entity_count_before=before,
            entity_count_after=after,
            save_memory_attempts=len(saves),
            save_memory_ok=0,
            link_memory_attempts=len(links),
            link_memory_ok=0,
            relation_count_before=rel_before,
            relation_count_after=rel_after,
            saves=saves,
            links=links,
            errors=[f"agent interrupted on tool {turn_out.tool_name}"],
        )

    verify_errors = verify_save_records(
        saves,
        conversation_id=conversation_id,
        require_conversation_tag=require_conversation_tag,
        expected_source=memory_source,
    )
    ok_count = sum(1 for s in saves if s.error is None and s.verified_in_db)
    link_ok_count = sum(1 for lk in links if lk.error is None and lk.verified_created)
    link_skip_count = sum(
        1 for lk in links if lk.error and str(lk.error).startswith("Link skipped:")
    )
    errors = list(verify_errors)
    if ok_count < min_successful_saves:
        errors.append(
            f"expected at least {min_successful_saves} verified save_memory calls, got {ok_count}"
        )
    link_hard_failures = 0
    for idx, lk in enumerate(links, start=1):
        if lk.error and not str(lk.error).startswith("Link skipped:"):
            link_hard_failures += 1
            errors.append(f"link #{idx} failed: {lk.error}")
    if link_skip_count:
        errors.append(
            f"{link_skip_count} link_memories call(s) skipped — see link errors above"
        )

    save_verify_failures = len(verify_errors)
    status = _facts_import_status(
        ok_count=ok_count,
        min_successful_saves=min_successful_saves,
        save_verify_failures=save_verify_failures,
        link_hard_failures=link_hard_failures,
        link_skip_count=link_skip_count,
        strict_links=strict_links,
    )
    return FactsImportResult(
        conversation_id=conversation_id,
        facts_path=str(facts_path),
        status=status,
        agent_reply=str(turn_out),
        entity_count_before=before,
        entity_count_after=after,
        save_memory_attempts=len(saves),
        save_memory_ok=ok_count,
        link_memory_attempts=len(links),
        link_memory_ok=link_ok_count,
        relation_count_before=rel_before,
        relation_count_after=rel_after,
        saves=saves,
        links=links,
        errors=errors,
    )
