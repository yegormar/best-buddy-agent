"""Multimodal user prompts (native vision via pydantic-ai)."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai.messages import BinaryContent, UserContent

DEFAULT_PHOTO_PROMPT = "The user sent a photo."


@dataclass(frozen=True, slots=True)
class UserImage:
    """One image attachment for a turn."""

    data: bytes
    media_type: str = "image/jpeg"


def build_native_user_prompt(
    user_text: str,
    images: list[UserImage],
) -> str | list[str | UserContent]:
    """Build pydantic-ai user input: text plus optional image parts."""
    if not images:
        return user_text

    text = (user_text or "").strip() or DEFAULT_PHOTO_PROMPT
    parts: list[str | UserContent] = [text]
    for img in images:
        parts.append(BinaryContent(data=img.data, media_type=img.media_type))
    return parts


def image_trace_summary(images: list[UserImage]) -> str:
    if not images:
        return ""
    lines = []
    for i, img in enumerate(images, start=1):
        lines.append(
            f"image[{i}]: {len(img.data)} bytes, media_type={img.media_type}"
        )
    return "\n".join(lines)
