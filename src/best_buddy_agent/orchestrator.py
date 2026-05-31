"""Main agent orchestration — delegates to pydantic-ai agent_runtime."""

from __future__ import annotations

from .agent_runtime import InterruptResult, run_turn
from .config import AgentConfig

__all__ = ["run_agent_once", "InterruptResult"]


def run_agent_once(
    *,
    config: AgentConfig,
    thread_id: str,
    user_text: str,
    timeout_sec: int = 90,
    approval_resolver=None,
) -> str | InterruptResult:
    """Run one agent turn. Returns final text or InterruptResult for HITL."""
    return run_turn(
        config,
        thread_id,
        user_text,
        timeout_sec=timeout_sec,
        approval_resolver=approval_resolver,
    )
