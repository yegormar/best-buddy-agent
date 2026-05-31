"""Human-in-the-loop approval contracts for deferred tools and workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from pydantic_ai.messages import ModelMessage


class ApprovalResolver(Protocol):
    """Resolve whether a deferred tool or workflow step may proceed."""

    def __call__(self, context: dict[str, Any]) -> bool:
        ...


@dataclass(slots=True)
class InterruptResult:
    """Agent paused for human approval before running a destructive tool."""

    type: str = "approval_required"
    tool_name: str = ""
    tool_call_id: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    pending: list[dict[str, Any]] = field(default_factory=list)
    message_history: list[ModelMessage] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "tool_name": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "args": self.args,
            "message": self.message,
            "pending": self.pending,
        }


def fixed_approval_resolver(approved: bool) -> ApprovalResolver:
    """Return a resolver that always approves or denies."""

    def _resolve(_context: dict[str, Any]) -> bool:
        return approved

    return _resolve


def cli_approval_resolver(context: dict[str, Any]) -> bool:
    """Prompt stdin for approve/deny (used by CLI and tests)."""
    tool = context.get("tool_name") or context.get("tool") or "tool"
    args = context.get("args") or {}
    msg = context.get("message") or f"Approve {tool}?"
    print(f"\n[approval required] {msg}")
    if args:
        print(f"  args: {args}")
    while True:
        ans = input("Approve? [y/N]: ").strip().lower()
        if ans in {"y", "yes"}:
            return True
        if ans in {"n", "no", ""}:
            return False
        print("Please answer y or n.")
