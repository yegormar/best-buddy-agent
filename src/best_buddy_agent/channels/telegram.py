"""Telegram long-polling channel for Best Buddy."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from ..agent_runtime import InterruptResult, TurnResult, resume_turn
from ..config import AgentConfig, TelegramSettings
from ..runtime import chat_once
from ..threads import create_thread
from .telegram_format import split_message

log = logging.getLogger(__name__)

MAX_TG_MESSAGE_LEN = 4096
CALLBACK_APPROVE = "interrupt_approve"
CALLBACK_DENY = "interrupt_deny"
_PENDING_TTL_SECONDS = 3600

_pending_by_chat: dict[int, PendingApproval] = {}
_running = False
_app: Any = None


@dataclass(slots=True)
class PendingApproval:
    interrupt: InterruptResult
    thread_id: str
    last_user_text: str
    config: AgentConfig
    created_at: float


def is_authorized(user_id: int | None, allowed_user_id: int | None) -> bool:
    if user_id is None or allowed_user_id is None:
        return False
    return int(user_id) == int(allowed_user_id)


def default_thread_id(chat_id: int) -> str:
    return f"telegram:dm:{chat_id}"


def new_thread_id(chat_id: int) -> str:
    suffix = uuid.uuid4().hex[:8]
    return f"telegram:dm:{chat_id}:{suffix}"


def format_interrupt(interrupt: InterruptResult) -> str:
    lines = [
        interrupt.message or f"Approval required for {interrupt.tool_name or 'tool'}."
    ]
    if interrupt.tool_name:
        lines.append(f"Tool: {interrupt.tool_name}")
    if interrupt.args:
        lines.append(f"Args: {interrupt.args}")
    return "\n".join(lines)


def _cleanup_stale_pending() -> None:
    now = time.time()
    stale = [
        cid
        for cid, pending in _pending_by_chat.items()
        if now - pending.created_at > _PENDING_TTL_SECONDS
    ]
    for cid in stale:
        _pending_by_chat.pop(cid, None)


def has_pending(chat_id: int) -> bool:
    _cleanup_stale_pending()
    return chat_id in _pending_by_chat


def clear_pending(chat_id: int) -> None:
    _pending_by_chat.pop(chat_id, None)


def run_turn_sync(
    config: AgentConfig,
    thread_id: str,
    user_text: str,
) -> TurnResult:
    create_thread(thread_id, name=f"telegram:{thread_id}")
    return chat_once(
        config=config,
        thread_id=thread_id,
        user_text=user_text,
        approval_resolver=None,
    )


def resume_turn_sync(
    pending: PendingApproval,
    *,
    approved: bool,
) -> TurnResult:
    return resume_turn(
        pending.config,
        pending.thread_id,
        pending.last_user_text,
        pending.interrupt,
        approved=approved,
        approval_resolver=None,
    )


async def send_text_chunks(chat: Any, text: str) -> None:
    for chunk in split_message(text or "_(No response)_"):
        await chat.send_message(chunk)


async def send_interrupt_prompt(chat: Any, interrupt: InterruptResult) -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Approve", callback_data=CALLBACK_APPROVE),
                InlineKeyboardButton("Deny", callback_data=CALLBACK_DENY),
            ]
        ]
    )
    await chat.send_message(format_interrupt(interrupt), reply_markup=keyboard)


def _get_thread_id(context: Any, chat_id: int) -> str:
    thread_id = context.chat_data.get("thread_id")
    if not thread_id:
        thread_id = default_thread_id(chat_id)
        context.chat_data["thread_id"] = thread_id
    return str(thread_id)


async def _run_agent_for_message(
    update: Any,
    context: Any,
    *,
    config: AgentConfig,
    user_text: str,
) -> None:
    from telegram.ext import ContextTypes

    _ = ContextTypes  # type hint anchor for PTB context
    chat_id = update.effective_chat.id
    msg = update.message

    if has_pending(chat_id):
        await msg.reply_text(
            "There is a pending approval. Tap Approve or Deny on the previous message first."
        )
        return

    thread_id = _get_thread_id(context, chat_id)
    await update.effective_chat.send_action("typing")

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: run_turn_sync(config, thread_id, user_text),
        )
    except Exception as exc:
        log.exception("Agent error for chat %s: %s", chat_id, exc)
        await msg.reply_text(f"Error: {exc}")
        return

    if isinstance(result, InterruptResult):
        _pending_by_chat[chat_id] = PendingApproval(
            interrupt=result,
            thread_id=thread_id,
            last_user_text=user_text,
            config=config,
            created_at=time.time(),
        )
        await send_interrupt_prompt(update.effective_chat, result)
        return

    await send_text_chunks(update.effective_chat, str(result))


async def handle_message(
    update: Any,
    context: Any,
    *,
    config: AgentConfig,
    allowed_user_id: int,
) -> None:
    user = update.effective_user
    if not is_authorized(user.id if user else None, allowed_user_id):
        log.warning("Rejected unauthorized Telegram user %s", getattr(user, "id", None))
        return

    text = (update.message.text or "").strip()
    if not text:
        return

    await _run_agent_for_message(update, context, config=config, user_text=text)


async def handle_callback(
    update: Any,
    context: Any,
    *,
    config: AgentConfig,
    allowed_user_id: int,
) -> None:
    query = update.callback_query
    await query.answer()

    if not is_authorized(
        query.from_user.id if query.from_user else None,
        allowed_user_id,
    ):
        return

    chat_id = update.effective_chat.id
    data = query.data or ""

    if data.startswith(("deadline:approve:", "deadline:approve_cal:", "deadline:dismiss:")):
        from ..deadline_watch.scanner import handle_deadline_callback

        try:
            msg = handle_deadline_callback(data, config)
        except Exception as exc:
            log.exception("Deadline callback failed: %s", exc)
            await query.edit_message_text(f"Error: {exc}")
            return
        await query.edit_message_text(msg)
        return

    if data not in {CALLBACK_APPROVE, CALLBACK_DENY}:
        await query.edit_message_text("Unknown action.")
        return

    pending = _pending_by_chat.pop(chat_id, None)
    if pending is None:
        await query.edit_message_text("No pending approval.")
        return

    approved = data == CALLBACK_APPROVE
    action = "Approved" if approved else "Denied"
    await query.edit_message_text(f"{action} — processing…")
    await update.effective_chat.send_action("typing")

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: resume_turn_sync(pending, approved=approved),
        )
    except Exception as exc:
        log.exception("Resume error for chat %s: %s", chat_id, exc)
        await update.effective_chat.send_message(f"Error: {exc}")
        return

    if isinstance(result, InterruptResult):
        _pending_by_chat[chat_id] = PendingApproval(
            interrupt=result,
            thread_id=pending.thread_id,
            last_user_text=pending.last_user_text,
            config=pending.config,
            created_at=time.time(),
        )
        await send_interrupt_prompt(update.effective_chat, result)
        return

    await send_text_chunks(update.effective_chat, str(result))


async def cmd_start(
    update: Any,
    context: Any,
    *,
    config: AgentConfig,
    allowed_user_id: int,
) -> None:
    if not is_authorized(
        update.effective_user.id if update.effective_user else None,
        allowed_user_id,
    ):
        return
    name = config.assistant_name
    await update.message.reply_text(
        f"{name} is ready. Send a message to chat.\n"
        "Commands: /help, /newthread"
    )


async def cmd_help(
    update: Any,
    context: Any,
    *,
    config: AgentConfig,
    allowed_user_id: int,
) -> None:
    if not is_authorized(
        update.effective_user.id if update.effective_user else None,
        allowed_user_id,
    ):
        return
    trace_hint = ""
    if config.log_enabled and config.log_file:
        trace_hint = f"\nTrace log: {config.log_file}"
    await update.message.reply_text(
        f"{config.assistant_name} — Best Buddy on Telegram\n\n"
        "/newthread — start a fresh conversation (history only; memory is shared)\n"
        "Ask BB to save preferences with save_memory; verify with list_memories."
        f"{trace_hint}"
    )


async def cmd_newthread(
    update: Any,
    context: Any,
    *,
    allowed_user_id: int,
) -> None:
    if not is_authorized(
        update.effective_user.id if update.effective_user else None,
        allowed_user_id,
    ):
        return
    chat_id = update.effective_chat.id
    clear_pending(chat_id)
    thread_id = new_thread_id(chat_id)
    context.chat_data["thread_id"] = thread_id
    create_thread(thread_id, name=f"telegram:{thread_id}")
    await update.message.reply_text("Started a new conversation thread.")


def build_application(
    config: AgentConfig,
    settings: TelegramSettings,
) -> Any:
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        CommandHandler,
        MessageHandler,
        filters,
    )

    allowed = settings.allowed_user_id
    assert allowed is not None

    async def _post_init(application: Any) -> None:
        import asyncio

        from ..notifications.telegram_notifier import register_telegram_notifier
        from ..services.bootstrap import start_background_services

        register_telegram_notifier(
            application.bot,
            asyncio.get_running_loop(),
            chat_id=int(allowed),
        )
        start_background_services(config, settings)

    async def _post_shutdown(_application: Any) -> None:
        from ..services.bootstrap import stop_background_services

        stop_background_services()

    app = (
        Application.builder()
        .token(settings.bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    async def on_message(update: Any, context: Any) -> None:
        await handle_message(update, context, config=config, allowed_user_id=allowed)

    async def on_callback(update: Any, context: Any) -> None:
        await handle_callback(update, context, config=config, allowed_user_id=allowed)

    async def on_start(update: Any, context: Any) -> None:
        await cmd_start(update, context, config=config, allowed_user_id=allowed)

    async def on_help(update: Any, context: Any) -> None:
        await cmd_help(update, context, config=config, allowed_user_id=allowed)

    async def on_newthread(update: Any, context: Any) -> None:
        await cmd_newthread(update, context, allowed_user_id=allowed)

    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("help", on_help))
    app.add_handler(CommandHandler("newthread", on_newthread))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_handler(CallbackQueryHandler(on_callback))
    return app


def run_polling(config: AgentConfig, settings: TelegramSettings) -> None:
    """Start Telegram long-polling until interrupted (Ctrl+C)."""
    global _app, _running

    if _running:
        log.info("Telegram bot already running")
        return

    _app = build_application(config, settings)
    _running = True
    log.info(
        "Telegram bot polling (allowed_user_id=%s)",
        settings.allowed_user_id,
    )
    try:
        # Blocking entry point; do not wrap in asyncio.run (PTB manages its own loop).
        _app.run_polling(drop_pending_updates=True)
    finally:
        _running = False
        _app = None
