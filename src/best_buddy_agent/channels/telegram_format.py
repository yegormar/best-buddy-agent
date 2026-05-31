"""Telegram message formatting helpers."""

from __future__ import annotations

MAX_TG_MESSAGE_LEN = 4096


def split_message(text: str, max_len: int = MAX_TG_MESSAGE_LEN) -> list[str]:
    """Split long text at paragraph or line boundaries."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break

        break_at = max_len
        para = remaining.rfind("\n\n", 0, max_len)
        if para > max_len // 2:
            break_at = para + 2
        else:
            line = remaining.rfind("\n", 0, max_len)
            if line > max_len // 2:
                break_at = line + 1
            else:
                space = remaining.rfind(" ", 0, max_len)
                if space > max_len // 2:
                    break_at = space + 1

        chunks.append(remaining[:break_at].rstrip())
        remaining = remaining[break_at:].lstrip()

    return [c for c in chunks if c]
