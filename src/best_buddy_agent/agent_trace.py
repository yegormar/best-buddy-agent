"""Agent run tracing via config-driven trace_block files."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)

from .config import AgentConfig
from .trace_logging import trace_block

_BLOCK_RE = re.compile(
    r"^===== .+? \| (.+?) =====\n(.*?)\n===== END =====$",
    re.MULTILINE | re.DOTALL,
)


def read_trace_blocks(path) -> list[tuple[str, str]]:
    """Parse trace file into (title, body) pairs for tests."""
    text = path.read_text(encoding="utf-8")
    return [(m.group(1), m.group(2).strip()) for m in _BLOCK_RE.finditer(text)]


def _body_or_redacted(config: AgentConfig, title: str, full: str) -> str:
    if title in {"INSTRUCTIONS", "MESSAGE HISTORY", "MODEL REQUEST"} and not config.log_prompts:
        digest = hashlib.sha256(full.encode("utf-8")).hexdigest()[:12]
        return f"len={len(full)} sha256={digest} [redacted: logging.log_prompts=false]"
    if title in {"MODEL RESPONSE", "TOOL RESULT"} and not config.log_responses:
        return f"len={len(full)} [redacted: logging.log_responses=false]"
    return full


def trace_routing_snapshot(
    config: AgentConfig,
    *,
    thread_id: str,
    user_text: str,
    recall_meta: dict[str, Any],
    memory_block: str,
    instructions_text: str,
    history_lines: list[str],
    tool_catalog: list[tuple[str, str]],
    max_tool_iterations: int,
) -> None:
    if not config.log_enabled:
        return
    lines = [
        "router: LLM (qwen/ollama) chooses text reply or tool calls from the catalog below",
        f"thread_id: {thread_id}",
        f"user_text: {user_text}",
        f"max_tool_iterations: {max_tool_iterations}",
        "",
        "=== auto-recall (Python, before LLM) ===",
        f"recall_query: {recall_meta.get('recall_query', '')!r}",
        f"recall_path: {recall_meta.get('recall_path', 'none')}",
        f"injected_subjects: {recall_meta.get('injected_subjects', [])}",
        f"memory_lines_in_system: {len(recall_meta.get('injected_subjects', []))}",
        "",
        "=== system message (sent once to the model) ===",
        _body_or_redacted(config, "ROUTING SNAPSHOT", instructions_text),
        "",
        "=== prior chat (this thread only; current user line sent separately) ===",
    ]
    if history_lines:
        lines.extend(history_lines)
    else:
        lines.append("(none)")
    lines.append(f"USER (this turn, once): {user_text}")
    lines.extend(
        [
            "",
            "=== tool catalog ===",
            *(f"  {name}: {desc}" for name, desc in tool_catalog),
            "",
            "wire summary: one system instructions message + message_history + one user prompt",
        ]
    )
    trace_block(config, "ROUTING SNAPSHOT", "\n".join(lines))


def trace_turn_start(
    config: AgentConfig,
    *,
    thread_id: str,
    user_text: str,
    workflow_context: dict[str, Any] | None,
    model_label: str,
) -> None:
    if not config.log_enabled:
        return
    lines = [
        f"thread_id: {thread_id}",
        f"model: {model_label}",
        f"user_text:\n{user_text}",
    ]
    if workflow_context:
        lines.append(
            "workflow_context:\n"
            + json.dumps(workflow_context, ensure_ascii=False, indent=2)
        )
    trace_block(config, "TURN START", "\n".join(lines))


def trace_instructions(config: AgentConfig, text: str) -> None:
    trace_block(config, "INSTRUCTIONS", _body_or_redacted(config, "INSTRUCTIONS", text))


def trace_message_history(config: AgentConfig, history: list[ModelMessage]) -> None:
    if not config.log_enabled or not config.log_message_history:
        return
    lines = [f"message_count: {len(history)}"]
    for i, msg in enumerate(history):
        if isinstance(msg, ModelRequest):
            parts = len(msg.parts)
            lines.append(f"  [{i}] request parts={parts}")
            if config.log_prompts:
                for p in msg.parts:
                    lines.append(f"      {p!r}")
        elif isinstance(msg, ModelResponse):
            parts = len(msg.parts)
            lines.append(f"  [{i}] response parts={parts}")
            if config.log_prompts:
                for p in msg.parts:
                    lines.append(f"      {p!r}")
        else:
            lines.append(f"  [{i}] {type(msg).__name__}")
    trace_block(config, "MESSAGE HISTORY", _body_or_redacted(config, "MESSAGE HISTORY", "\n".join(lines)))


def trace_tool_call(config: AgentConfig, name: str, args: dict[str, Any]) -> None:
    if not config.log_enabled:
        return
    if not config.log_tool_args:
        body = f"tool: {name}\nargs_len: {len(json.dumps(args))}"
    else:
        body = f"tool: {name}\nargs:\n{json.dumps(args, ensure_ascii=False, indent=2)}"
    trace_block(config, "TOOL CALL", body)


def trace_tool_result(config: AgentConfig, name: str, result: str, *, error: bool = False) -> None:
    prefix = "error" if error else "result"
    if config.log_responses:
        body = f"tool: {name}\n{prefix}:\n{result}"
    else:
        body = f"tool: {name}\n{prefix}_len: {len(result)}"
    trace_block(config, "TOOL RESULT", _body_or_redacted(config, "TOOL RESULT", body))


def trace_deferred_pending(config: AgentConfig, pending: list[dict[str, Any]]) -> None:
    trace_block(
        config,
        "DEFERRED TOOL PENDING",
        json.dumps(pending, ensure_ascii=False, indent=2),
    )


def trace_deferred_resume(config: AgentConfig, approved: bool, detail: str) -> None:
    trace_block(config, "DEFERRED RESUME", f"approved: {approved}\n{detail}")


def trace_llm_wire_http(
    config: AgentConfig,
    *,
    kind: str,
    seq: int,
    headline: str,
    body: str,
) -> None:
    """Log one HTTP request or response body (Ollama /v1/chat/completions)."""
    if not config.log_enabled or not config.log_llm_wire:
        return
    trace_block(
        config,
        f"LLM WIRE {kind}",
        f"call: {seq}\n{headline}\n\n{body.rstrip()}",
    )


def trace_turn_end(
    config: AgentConfig,
    *,
    elapsed_ms: int,
    output_len: int,
    message_count: int,
    error: str | None = None,
) -> None:
    lines = [
        f"elapsed_ms: {elapsed_ms}",
        f"output_len: {output_len}",
        f"messages_in_run: {message_count}",
    ]
    if error:
        lines.append(f"error: {error}")
    trace_block(config, "TURN END", "\n".join(lines))


def log_run_messages(config: AgentConfig, messages: list[ModelMessage]) -> None:
    """Walk all messages from a completed run and emit trace blocks."""
    if not config.log_enabled:
        return
    step = 0
    for msg in messages:
        if isinstance(msg, ModelRequest):
            step += 1
            parts_text = "\n".join(repr(p) for p in msg.parts)
            trace_block(
                config,
                "MODEL REQUEST",
                _body_or_redacted(config, "MODEL REQUEST", f"step={step}\n{parts_text}"),
            )
        elif isinstance(msg, ModelResponse):
            parts_lines: list[str] = []
            for p in msg.parts:
                if isinstance(p, ToolCallPart):
                    args = p.args if isinstance(p.args, dict) else {}
                    trace_tool_call(config, p.tool_name, args)
                    parts_lines.append(f"tool_call: {p.tool_name}")
                else:
                    parts_lines.append(repr(p))
            trace_block(
                config,
                "MODEL RESPONSE",
                _body_or_redacted(config, "MODEL RESPONSE", "\n".join(parts_lines)),
            )

    for msg in messages:
        if isinstance(msg, ModelRequest):
            for p in msg.parts:
                if isinstance(p, ToolReturnPart):
                    trace_tool_result(config, p.tool_name or "tool", str(p.content))
