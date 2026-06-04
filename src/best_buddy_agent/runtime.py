"""Runnable interactive Best Buddy agent runtime."""

from __future__ import annotations

import time

from .agent_runtime import InterruptResult, TurnResult, run_turn
from .multimodal import UserImage
from .config import AgentConfig
from .threads import create_thread
from .trace_logging import trace_block


def chat_once(
    *,
    config: AgentConfig,
    thread_id: str,
    user_text: str,
    timeout_sec: int = 90,  # noqa: ARG001
    approval_resolver=None,
    pending_interrupt: InterruptResult | None = None,
    interrupt_approved: bool | None = None,
    user_images: list[UserImage] | None = None,
) -> TurnResult:
    """Run one chat turn; history persisted in thread_message_batches by run_turn."""
    turn_t0 = time.perf_counter()
    create_thread(thread_id, name=f"chat:{thread_id}")

    if config.log_enabled:
        trace_block(
            config,
            "CHAT TURN START",
            f"thread_id: {thread_id}\nuser_text:\n{user_text}",
        )

    if pending_interrupt is not None and interrupt_approved is not None:
        from .agent_runtime import resume_turn

        reply = resume_turn(
            config,
            thread_id,
            user_text,
            pending_interrupt,
            approved=interrupt_approved,
            approval_resolver=approval_resolver,
        )
    else:
        reply = run_turn(
            config,
            thread_id,
            user_text,
            timeout_sec=timeout_sec,
            approval_resolver=approval_resolver,
            user_images=user_images,
        )

    elapsed_ms = int((time.perf_counter() - turn_t0) * 1000)
    if config.log_enabled:
        reply_preview = (
            f"[interrupt: {reply.tool_name}]"
            if isinstance(reply, InterruptResult)
            else str(reply)[:500]
        )
        trace_block(
            config,
            "CHAT TURN END",
            f"thread_id: {thread_id}\nelapsed_ms: {elapsed_ms}\nreply:\n{reply_preview}",
        )
    return reply
