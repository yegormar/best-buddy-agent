"""Thread-safe proactive Telegram messages from background scheduler threads."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

log = logging.getLogger(__name__)

_bot: Any = None
_loop: asyncio.AbstractEventLoop | None = None
_chat_id: int | None = None
_message_format: str = "html"


def register_telegram_notifier(
    bot: Any,
    loop: asyncio.AbstractEventLoop,
    *,
    chat_id: int,
    message_format: str = "html",
) -> None:
    """Register the running PTB bot for cross-thread proactive sends."""
    global _bot, _loop, _chat_id, _message_format
    from ..channels.telegram_format import normalize_message_format

    _bot = bot
    _loop = loop
    _chat_id = int(chat_id)
    _message_format = normalize_message_format(message_format)
    log.info(
        "Telegram proactive notifier registered (chat_id=%s, message_format=%s)",
        chat_id,
        _message_format,
    )


def is_registered() -> bool:
    return _bot is not None and _loop is not None and _chat_id is not None


async def _send_async(
    text: str,
    *,
    reply_markup: Any = None,
    parse_mode: str | None = None,
    message_format: str | None = None,
) -> None:
    if _bot is None or _chat_id is None:
        raise RuntimeError("Telegram notifier not registered")
    from ..channels.telegram_format import prepare_telegram_chunks, strip_html_to_plain

    fmt = message_format if message_format is not None else _message_format
    if parse_mode is not None:
        chunks = [(text or "_(empty)_", parse_mode)]
    else:
        chunks = prepare_telegram_chunks(text, fmt)

    for i, (chunk, chunk_parse_mode) in enumerate(chunks):
        try:
            await _bot.send_message(
                chat_id=_chat_id,
                text=chunk,
                reply_markup=reply_markup if i == 0 else None,
                parse_mode=chunk_parse_mode,
            )
        except Exception:
            plain = strip_html_to_plain(chunk) if chunk_parse_mode else chunk
            await _bot.send_message(
                chat_id=_chat_id,
                text=plain,
                reply_markup=reply_markup if i == 0 else None,
                parse_mode=None,
            )


def send_proactive(
    text: str,
    *,
    reply_markup: Any = None,
    parse_mode: str | None = None,
    timeout_sec: float = 30.0,
) -> None:
    """Send a proactive message from a sync context (scheduler thread)."""
    if not is_registered():
        log.warning("Telegram notifier not registered — dropping message: %s", (text or "")[:80])
        return
    assert _loop is not None
    future = asyncio.run_coroutine_threadsafe(
        _send_async(text, reply_markup=reply_markup, parse_mode=parse_mode),
        _loop,
    )
    try:
        future.result(timeout=timeout_sec)
    except Exception:
        log.exception("Proactive Telegram send failed")


def make_notifier() -> Callable[[str], None]:
    """Return a sync notifier callback for workflow_engine."""

    def _notify(message: str) -> None:
        send_proactive(message)

    return _notify
