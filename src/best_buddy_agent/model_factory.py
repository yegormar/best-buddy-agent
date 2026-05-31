"""Shared Ollama model and agent capability construction."""

from __future__ import annotations

from typing import Any

from pydantic_ai.capabilities import Thinking
from pydantic_ai.models import Model
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider

from .config import AgentConfig

# Documented exception: Ollama /v1 ignores unified thinking=False for some models (Qwen3).
# See https://github.com/ollama/ollama/issues/15029
_OLLAMA_THINKING_OFF_SETTINGS: dict[str, object] = {
    "openai_reasoning_effort": "none",
}


def _use_ollama_reasoning_effort_none(model_name: str) -> bool:
    """Whether to set openai_reasoning_effort=none when llm_think=false.

    Qwen 3.5 on Ollama breaks tool/structured output if reasoning_effort=none is set;
    use Thinking(effort=False) only (see examples/llm_pydantic_call.py).
    """
    name = model_name.lower()
    return "qwen3.5" not in name and "qwen3_5" not in name


def build_ollama_model(config: AgentConfig) -> OllamaModel:
    """Build the production Ollama model (OpenAI-compatible /v1)."""
    base = f"{config.ollama_base_url.rstrip('/')}/v1"
    http_client = None
    if config.log_llm_wire:
        from .llm_wire_logging import create_wire_logging_http_client

        http_client = create_wire_logging_http_client(config)
    provider = OllamaProvider(base_url=base, http_client=http_client)
    settings: dict[str, object] = {
        "temperature": config.llm_temperature,
        "top_p": config.llm_top_p,
        "num_ctx": config.llm_num_ctx,
    }
    if not config.llm_think and _use_ollama_reasoning_effort_none(config.llm_model):
        settings.update(_OLLAMA_THINKING_OFF_SETTINGS)
    return OllamaModel(
        config.llm_model,
        provider=provider,
        settings=settings,
    )


def build_thinking_capabilities(config: AgentConfig) -> list[Any]:
    """Thinking control via pydantic-ai capability (portable across providers)."""
    if config.llm_think:
        return [Thinking(effort=True)]
    return [Thinking(effort=False)]


def agent_config_fingerprint(config: AgentConfig) -> tuple[object, ...]:
    """Cache key for module-level Agent singleton."""
    return (
        config.llm_model,
        config.llm_host,
        config.llm_port,
        config.llm_think,
        config.llm_num_ctx,
        config.llm_temperature,
        config.llm_top_p,
        config.max_tool_iterations,
        config.reliability_required,
        config.log_enabled,
        str(config.log_file) if config.log_file else "",
        config.log_prompts,
        config.log_responses,
        config.log_llm_wire,
        hash(config.prompts.fingerprint()),
        config.gmail.enabled,
        config.gmail.is_ready(),
    )
