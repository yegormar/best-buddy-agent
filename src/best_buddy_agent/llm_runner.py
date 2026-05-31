"""One-shot LLM calls via pydantic-ai (same model stack as the agent)."""

from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.models import Model

from .config import AgentConfig
from .model_factory import build_ollama_model, build_thinking_capabilities


def run_text_completion(
    config: AgentConfig,
    prompt: str,
    *,
    model: Model | None = None,
    instructions: str | None = None,
) -> str:
    """Run a single-turn text completion using the shared Ollama model."""
    llm = model or build_ollama_model(config)
    system_instructions = instructions or config.prompts.get("llm/text_completion_system")
    agent = Agent(
        llm,
        output_type=str,
        instructions=system_instructions,
        capabilities=build_thinking_capabilities(config),
    )
    result = agent.run_sync(prompt)
    text = str(result.output or "").strip()
    if not text:
        raise RuntimeError("LLM returned empty text")
    return text
