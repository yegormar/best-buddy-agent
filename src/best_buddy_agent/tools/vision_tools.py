"""Vision tools — reload cached photos for follow-up inspection."""

from __future__ import annotations

from pydantic_ai import Agent

from ..config import AgentConfig
from ..model_factory import build_ollama_model, build_thinking_capabilities
from ..multimodal import UserImage, build_native_user_prompt
from ..vision_cache import (
    VisionCacheError,
    _media_type_for_suffix,
    resolve_cached_image_path,
)


class ToolError(Exception):
    """Raised when a vision tool cannot run."""


def revisit_image(
    config: AgentConfig,
    image_name: str,
    question: str,
) -> str:
    """Run a one-shot native vision turn on a cached photo by filename."""
    q = (question or "").strip()
    if not q:
        raise ToolError("question must be non-empty")

    try:
        path = resolve_cached_image_path(image_name)
    except VisionCacheError as exc:
        raise ToolError(str(exc)) from exc

    data = path.read_bytes()
    if not data:
        raise ToolError(f"cached image is empty: {image_name}")

    media_type = _media_type_for_suffix(path.suffix)
    prompt = build_native_user_prompt(
        q,
        [UserImage(data=data, media_type=media_type)],
    )

    llm = build_ollama_model(config)
    agent = Agent(
        llm,
        output_type=str,
        instructions=(
            "You are inspecting a cached photo the user sent earlier. "
            "Answer the question using only what you see in the image."
        ),
        capabilities=build_thinking_capabilities(config),
    )
    try:
        result = agent.run_sync(prompt)
    except Exception as exc:
        raise ToolError(f"vision model failed: {exc}") from exc

    text = str(result.output or "").strip()
    if not text:
        raise ToolError("vision model returned empty text")
    return text
