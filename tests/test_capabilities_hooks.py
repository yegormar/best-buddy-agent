from __future__ import annotations

from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart

from best_buddy_agent.capabilities_hooks import build_capabilities
from best_buddy_agent.config import AgentConfig


from tests.conftest import load_test_config


def _minimal_config(**overrides) -> AgentConfig:
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp())
    cfg = load_test_config(tmp, system_prompt_override="sys")
    for key, value in overrides.items():
        object.__setattr__(cfg, key, value)
    return cfg


async def _async_identity(messages: list[ModelMessage]) -> list[ModelMessage]:
    return messages


def test_combined_history_processor_awaits_async_summarizer(monkeypatch):
    """Regression: sync wrapper around async summarization raised 'coroutine' is not iterable."""
    from pydantic_ai.capabilities.process_history import ProcessHistory

    monkeypatch.setattr(
        "pydantic_ai_summarization.create_summarization_processor",
        lambda **_kwargs: _async_identity,
    )

    class _StubCap:
        pass

    monkeypatch.setattr("pydantic_deep.PatchToolCallsCapability", _StubCap)
    monkeypatch.setattr("pydantic_deep.StuckLoopDetection", _StubCap)

    caps = build_capabilities(_minimal_config(), use_reliability=True)
    process_history = next(c for c in caps if isinstance(c, ProcessHistory))
    messages = [ModelRequest(parts=[UserPromptPart(content="hi")])]

    import asyncio

    result = asyncio.run(process_history.processor(messages))
    assert result == messages
