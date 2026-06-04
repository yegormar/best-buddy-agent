"""On-disk cache for inbound photos; strip pixels from persisted thread history."""

from __future__ import annotations

import os
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from pydantic_ai.messages import (
    BinaryContent,
    ModelMessage,
    ModelRequest,
    UserPromptPart,
)

from .threads import user_prompt_content_text

_CACHE_REF_RE = re.compile(
    r"\[Cached photo:\s*([^\]\s]+)\s*\]",
    re.IGNORECASE,
)
_SAFE_NAME_RE = re.compile(
    r"^[a-zA-Z][a-zA-Z0-9_]*_\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}\.[a-zA-Z0-9]+$",
)


class VisionCacheError(Exception):
    """Invalid or missing cached image."""


def _data_dir() -> Path:
    return Path(
        os.environ.get("BEST_BUDDY_AGENT_DATA_DIR", Path.home() / ".best_buddy_agent")
    ).expanduser().resolve()


def vision_cache_dir() -> Path:
    path = _data_dir() / "vision_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _media_type_for_suffix(suffix: str) -> str:
    ext = suffix.lower().lstrip(".")
    if ext in ("jpg", "jpeg"):
        return "image/jpeg"
    if ext == "png":
        return "image/png"
    if ext == "webp":
        return "image/webp"
    if ext == "gif":
        return "image/gif"
    return "image/jpeg"


def _suffix_for_media_type(media_type: str) -> str:
    mt = (media_type or "").lower()
    if "png" in mt:
        return ".png"
    if "webp" in mt:
        return ".webp"
    if "gif" in mt:
        return ".gif"
    return ".jpg"


def _normalize_prefix(prefix: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9_]+", "_", (prefix or "photo").strip())
    raw = raw.strip("_") or "photo"
    if not raw[0].isalpha():
        raw = f"img_{raw}"
    return raw


def make_cache_filename(prefix: str, *, media_type: str = "image/jpeg") -> str:
    """``{prefix}_yyyy_mm_dd_HH_MM_SS.ext``"""
    slug = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    return f"{_normalize_prefix(prefix)}_{slug}{_suffix_for_media_type(media_type)}"


def format_cache_reference(filename: str) -> str:
    return (
        f"[Cached photo: {filename}] "
        "Pixels are not kept in chat history. "
        f"Use revisit_image(image_name={filename!r}, question=...) to inspect the image again."
    )


def extract_cached_filename(text: str) -> str | None:
    if not text:
        return None
    match = _CACHE_REF_RE.search(text)
    if not match:
        return None
    return match.group(1).strip()


def cache_user_image(
    data: bytes,
    *,
    prefix: str = "photo",
    media_type: str = "image/jpeg",
) -> tuple[str, Path]:
    """Write bytes to vision_cache; return (filename, absolute path)."""
    filename = make_cache_filename(prefix, media_type=media_type)
    path = vision_cache_dir() / filename
    path.write_bytes(data)
    return filename, path


def resolve_cached_image_path(image_name: str) -> Path:
    """Resolve a cache filename to an on-disk path (no path traversal)."""
    name = Path(str(image_name or "").strip()).name
    if not name or name != image_name.strip():
        raise VisionCacheError("image_name must be a bare filename")
    if not _SAFE_NAME_RE.match(name):
        raise VisionCacheError(
            f"image_name must match prefix_yyyy_mm_dd_HH_MM_SS.ext (got {name!r})"
        )
    path = (vision_cache_dir() / name).resolve()
    if path.parent != vision_cache_dir().resolve():
        raise VisionCacheError("invalid image_name")
    if not path.is_file():
        raise VisionCacheError(f"cached image not found: {name}")
    return path


def _content_has_binary(content: object) -> bool:
    if not isinstance(content, list):
        return False
    return any(isinstance(part, BinaryContent) for part in content)


def strip_images_for_storage(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Replace multimodal user parts with text-only cache references."""
    stripped: list[ModelMessage] = []
    for msg in messages:
        if not isinstance(msg, ModelRequest):
            stripped.append(msg)
            continue
        new_parts = []
        changed = False
        for part in msg.parts:
            if not isinstance(part, UserPromptPart):
                new_parts.append(part)
                continue
            if not _content_has_binary(part.content):
                new_parts.append(part)
                continue
            text = user_prompt_content_text(part.content)
            filename = extract_cached_filename(text)
            if filename:
                new_text = format_cache_reference(filename)
            elif text:
                new_text = f"{text}\n[image removed from history]"
            else:
                new_text = "[image removed from history]"
            new_parts.append(replace(part, content=new_text))
            changed = True
        stripped.append(replace(msg, parts=new_parts) if changed else msg)
    return stripped
