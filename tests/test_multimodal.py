"""Multimodal prompt building."""

from __future__ import annotations

from pathlib import Path

from pydantic_ai.messages import BinaryContent, ModelRequest, UserPromptPart

from best_buddy_agent.multimodal import (
    DEFAULT_PHOTO_PROMPT,
    UserImage,
    build_native_user_prompt,
    image_trace_summary,
)


def test_build_native_text_only():
    assert build_native_user_prompt("hello", []) == "hello"


def test_build_native_with_image():
    img = UserImage(data=b"\xff\xd8\xff", media_type="image/jpeg")
    parts = build_native_user_prompt("what is this?", [img])
    assert isinstance(parts, list)
    assert parts[0] == "what is this?"
    assert isinstance(parts[1], BinaryContent)
    assert parts[1].data == img.data
    assert parts[1].media_type == "image/jpeg"


def test_build_native_default_text_without_caption():
    img = UserImage(data=b"x", media_type="image/jpeg")
    parts = build_native_user_prompt("", [img])
    assert parts[0] == DEFAULT_PHOTO_PROMPT


def test_image_trace_summary():
    assert image_trace_summary([]) == ""
    summary = image_trace_summary([UserImage(data=b"abc", media_type="image/jpeg")])
    assert "3 bytes" in summary
    assert "image/jpeg" in summary


def test_thread_conversation_rows_multimodal_prompt(tmp_path: Path):
    from best_buddy_agent.threads import append_turn_messages, thread_conversation_rows

    history = [
        ModelRequest(
            parts=[
                UserPromptPart(
                    content=[
                        "what is this?",
                        BinaryContent(data=b"\xff\xd8", media_type="image/jpeg"),
                    ]
                )
            ]
        )
    ]
    append_turn_messages("vision-thread", history)
    rows = thread_conversation_rows("vision-thread")
    assert rows[0]["content"] == "what is this?\n[image]"
