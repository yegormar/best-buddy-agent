"""Messaging channel adapters for Best Buddy."""

from .telegram_format import (
    MAX_TG_MESSAGE_LEN,
    escape_html,
    md_to_html,
    normalize_message_format,
    prepare_telegram_chunks,
    rewrite_gfm_tables,
    split_message,
    strip_html_to_plain,
)

__all__ = [
    "MAX_TG_MESSAGE_LEN",
    "escape_html",
    "md_to_html",
    "normalize_message_format",
    "prepare_telegram_chunks",
    "rewrite_gfm_tables",
    "split_message",
    "strip_html_to_plain",
]
