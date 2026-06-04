"""Vision cache and history stripping."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic_ai.messages import BinaryContent, ModelRequest, UserPromptPart

from best_buddy_agent.vision_cache import (
    VisionCacheError,
    cache_user_image,
    extract_cached_filename,
    format_cache_reference,
    make_cache_filename,
    resolve_cached_image_path,
    strip_images_for_storage,
    vision_cache_dir,
)


def test_make_cache_filename_pattern():
    name = make_cache_filename("tg_photo", media_type="image/jpeg")
    assert re.match(r"^tg_photo_\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}\.jpg$", name)


def test_cache_and_resolve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(tmp_path))
    data = b"\xff\xd8\xff\xfe"
    filename, path = cache_user_image(data, prefix="tg_photo", media_type="image/jpeg")
    assert path.is_file()
    assert path.read_bytes() == data
    assert resolve_cached_image_path(filename) == path.resolve()


def test_resolve_rejects_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(tmp_path))
    cache_user_image(b"x", prefix="tg_photo")
    with pytest.raises(VisionCacheError):
        resolve_cached_image_path("../etc/passwd")


def test_strip_images_for_storage():
    filename = "tg_photo_2026_06_03_12_00_00.jpg"
    ref = format_cache_reference(filename)
    msg = ModelRequest(
        parts=[
            UserPromptPart(
                content=[
                    f"what is this?\n{ref}",
                    BinaryContent(data=b"pixels", media_type="image/jpeg"),
                ]
            )
        ]
    )
    out = strip_images_for_storage([msg])
    part = out[0].parts[0]
    assert isinstance(part.content, str)
    assert "pixels" not in part.content
    assert filename in part.content
    assert "revisit_image" in part.content


def test_extract_cached_filename():
    name = "tg_photo_2026_06_03_12_00_00.jpg"
    text = format_cache_reference(name)
    assert extract_cached_filename(text) == name
