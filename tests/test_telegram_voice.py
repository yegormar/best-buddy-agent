"""Telegram voice handler tests (no real whisper)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from best_buddy_agent.channels import telegram as tg_mod
from best_buddy_agent.config import load_config
from tests.conftest import write_test_conf


def _config(tmp_path: Path, *, stt_enabled: bool):
    conf = write_test_conf(tmp_path)
    if stt_enabled:
        hf = tmp_path / "hf"
        cache = hf / "cache"
        cache.mkdir(parents=True)
        conf.write_text(
            conf.read_text(encoding="utf-8")
            + f"""
[stt]
enabled = true
device = cpu
model = tiny
compute_type_cpu = int8
compute_type_cuda = float16
beam_size = 5
temperature = 0.0
best_of = 5
patience = 1.0
condition_on_previous_text = true
vad_filter = true
vad_min_silence_duration_ms = 200
hf_home = {hf}
hf_hub_cache = {cache}
echo_transcript = false
""",
            encoding="utf-8",
        )
    return load_config(str(conf))


def test_handle_voice_disabled(tmp_path: Path):
    config = _config(tmp_path, stt_enabled=False)
    update = MagicMock()
    update.effective_user.id = 1
    update.message.voice = MagicMock()
    update.message.audio = None
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    asyncio.run(
        tg_mod.handle_voice(update, context, config=config, allowed_user_id=1)
    )
    update.message.reply_text.assert_awaited_once()
    assert "not enabled" in update.message.reply_text.await_args[0][0]


def test_handle_voice_transcribes_and_runs_agent(tmp_path: Path):
    config = _config(tmp_path, stt_enabled=True)
    update = MagicMock()
    update.effective_user.id = 1
    update.effective_chat.id = 42
    update.effective_chat.send_action = AsyncMock()
    voice = MagicMock(mime_type="audio/ogg")
    update.message.voice = voice
    update.message.audio = None
    update.message.caption = ""
    update.message.reply_text = AsyncMock()
    tg_file = MagicMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"fake"))
    voice.get_file = AsyncMock(return_value=tg_file)
    context = MagicMock()
    context.chat_data = {}

    with (
        patch(
            "best_buddy_agent.transcription.transcribe_bytes",
            return_value="hello from voice",
        ),
        patch.object(tg_mod, "_run_agent_for_message", new_callable=AsyncMock) as run_agent,
    ):
        asyncio.run(
            tg_mod.handle_voice(update, context, config=config, allowed_user_id=1)
        )

    run_agent.assert_awaited_once()
    assert run_agent.await_args.kwargs["user_text"] == "hello from voice"
