"""pydantic-ai capabilities (thinking, observability, reliability)."""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai.messages import ModelMessage

from .agent_context import redact_data_uris
from .config import AgentConfig
from .exceptions import ReliabilityUnavailableError
from .model_factory import build_thinking_capabilities

logger = logging.getLogger(__name__)


def _redact_history_processor(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Strip large data URIs from message text before model requests."""
    out: list[ModelMessage] = []
    for msg in messages:
        if hasattr(msg, "parts"):
            new_parts = []
            for part in msg.parts:
                content = getattr(part, "content", None)
                if isinstance(content, str):
                    from dataclasses import replace

                    new_parts.append(replace(part, content=redact_data_uris(content)))
                else:
                    new_parts.append(part)
            from dataclasses import replace as dc_replace

            out.append(dc_replace(msg, parts=new_parts))
        else:
            out.append(msg)
    return out


def build_capabilities(config: AgentConfig, *, use_reliability: bool = True) -> list[Any]:
    """Build agent capabilities: thinking, optional Logfire instrumentation, reliability."""
    caps: list[Any] = list(build_thinking_capabilities(config))

    if not use_reliability:
        return caps

    try:
        from pydantic_ai.capabilities.process_history import ProcessHistory
        from pydantic_ai_summarization import create_summarization_processor
        from pydantic_deep import PatchToolCallsCapability, StuckLoopDetection

        trigger_tokens = int(config.llm_num_ctx * 0.85)
        processor = create_summarization_processor(
            trigger=("tokens", trigger_tokens),
            keep=("messages", 12),
        )

        async def _combined_history_processor(messages: list[ModelMessage]) -> list[ModelMessage]:
            summarized = await processor(messages)
            return _redact_history_processor(summarized)

        caps.append(ProcessHistory(_combined_history_processor))
        caps.append(PatchToolCallsCapability())
        caps.append(StuckLoopDetection())
        logger.debug("Loaded pydantic-deep reliability capabilities")
    except Exception as exc:
        if config.reliability_required:
            raise ReliabilityUnavailableError(
                "agent.reliability_required=true but reliability extras are not installed. "
                'Install with: pip install -e ".[reliability]"'
            ) from exc
        logger.debug("Reliability capabilities unavailable: %s", exc)

    return caps
