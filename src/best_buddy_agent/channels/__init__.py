"""Messaging channel adapters for Best Buddy."""

from .telegram_format import MAX_TG_MESSAGE_LEN, split_message

__all__ = ["MAX_TG_MESSAGE_LEN", "split_message"]
