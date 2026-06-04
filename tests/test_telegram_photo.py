"""Telegram photo handler tests (no real Ollama)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from best_buddy_agent.channels import telegram as tg_mod
from best_buddy_agent.config import load_config
from best_buddy_agent.multimodal import DEFAULT_PHOTO_PROMPT, UserImage
from tests.conftest import write_test_conf


def _config(tmp_path: Path, *, vision_enabled: bool):
    conf = write_test_conf(tmp_path)
    if vision_enabled:
        conf.write_text(
            conf.read_text(encoding="utf-8")
            + """
[vision]
enabled = true
max_image_bytes = 10485760
""",
            encoding="utf-8",
        )
    return load_config(str(conf))


def test_handle_photo_disabled(tmp_path: Path):
    config = _config(tmp_path, vision_enabled=False)
    update = MagicMock()
    update.effective_user.id = 1
    update.message.photo = [MagicMock()]
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    asyncio.run(
        tg_mod.handle_photo(update, context, config=config, allowed_user_id=1)
    )
    update.message.reply_text.assert_awaited_once()
    assert "not enabled" in update.message.reply_text.await_args[0][0]


def test_handle_photo_downloads_and_runs_agent(tmp_path: Path):
    config = _config(tmp_path, vision_enabled=True)
    update = MagicMock()
    update.effective_user.id = 1
    update.effective_chat.id = 42
    update.effective_chat.send_action = AsyncMock()
    photo = MagicMock()
    update.message.photo = [photo]
    update.message.caption = "what is in this image?"
    update.message.reply_text = AsyncMock()
    tg_file = MagicMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"jpeg-bytes"))
    photo.get_file = AsyncMock(return_value=tg_file)
    context = MagicMock()
    context.chat_data = {}

    with (
        patch.object(tg_mod, "_run_agent_for_message", new_callable=AsyncMock) as run_agent,
        patch(
            "best_buddy_agent.channels.telegram.cache_user_image",
            return_value=("tg_photo_2026_06_03_12_00_00.jpg", Path("/tmp/x.jpg")),
        ),
    ):
        asyncio.run(
            tg_mod.handle_photo(update, context, config=config, allowed_user_id=1)
        )

    run_agent.assert_awaited_once()
    user_text = run_agent.await_args.kwargs["user_text"]
    assert "what is in this image?" in user_text
    assert "tg_photo_2026_06_03_12_00_00.jpg" in user_text
    assert "[Cached photo:" in user_text
    images = run_agent.await_args.kwargs["user_images"]
    assert len(images) == 1
    assert isinstance(images[0], UserImage)
    assert images[0].data == b"jpeg-bytes"


def test_handle_photo_default_caption(tmp_path: Path):
    config = _config(tmp_path, vision_enabled=True)
    update = MagicMock()
    update.effective_user.id = 1
    update.effective_chat.id = 42
    update.effective_chat.send_action = AsyncMock()
    photo = MagicMock()
    update.message.photo = [photo]
    update.message.caption = None
    update.message.reply_text = AsyncMock()
    tg_file = MagicMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"x"))
    photo.get_file = AsyncMock(return_value=tg_file)
    context = MagicMock()
    context.chat_data = {}

    with patch.object(tg_mod, "_run_agent_for_message", new_callable=AsyncMock) as run_agent:
        asyncio.run(
            tg_mod.handle_photo(update, context, config=config, allowed_user_id=1)
        )

    user_text = run_agent.await_args.kwargs["user_text"]
    assert user_text.startswith(DEFAULT_PHOTO_PROMPT)
    assert "[Cached photo:" in user_text
