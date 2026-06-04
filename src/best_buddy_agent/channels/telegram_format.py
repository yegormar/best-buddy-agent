"""Telegram message formatting helpers.

Markdown-to-HTML conversion is inspired by Thoth/channels/telegram.py (Apache-2.0).
GFM table rewriting follows Hermes gateway/platforms/telegram.py (row-group bullets).
"""

from __future__ import annotations

import re

MAX_TG_MESSAGE_LEN = 4096

_MESSAGE_FORMATS = frozenset({"plain", "html"})

# GFM delimiter row: | :--- | :--- | (not a lone --- horizontal rule)
_TABLE_SEPARATOR_RE = re.compile(
    r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*){1,}\|?\s*$"
)


def normalize_message_format(raw: str) -> str:
    """Return ``plain`` or ``html``; raise ValueError if invalid."""
    mode = (raw or "html").strip().lower()
    if mode not in _MESSAGE_FORMATS:
        raise ValueError(f"message_format must be one of: {', '.join(sorted(_MESSAGE_FORMATS))}")
    return mode


def escape_html(text: str) -> str:
    """Escape characters required by Telegram HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and "|" in stripped


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _render_table_block(table_block: list[str]) -> str:
    """Render a GFM table as bold row headings plus bullet lines."""
    if len(table_block) < 3:
        return "\n".join(table_block)

    headers = _split_table_row(table_block[0])
    if len(headers) < 2:
        return "\n".join(table_block)

    first_data = _split_table_row(table_block[2]) if len(table_block) > 2 else []
    has_row_label_col = len(first_data) == len(headers) + 1

    groups: list[str] = []
    for index, row in enumerate(table_block[2:], start=1):
        cells = _split_table_row(row)
        if has_row_label_col:
            heading = cells[0] if cells and cells[0] else f"Row {index}"
            data_cells = cells[1:]
        else:
            heading = next((c for c in cells if c), f"Row {index}")
            data_cells = cells

        if len(data_cells) < len(headers):
            data_cells.extend([""] * (len(headers) - len(data_cells)))
        elif len(data_cells) > len(headers):
            data_cells = data_cells[: len(headers)]

        bullets: list[str] = []
        for header, value in zip(headers, data_cells):
            if not has_row_label_col and value == heading:
                continue
            bullets.append(f"• {header}: {value}")

        groups.append("\n".join([f"**{heading}**", *bullets]))

    return "\n\n".join(groups)


def rewrite_gfm_tables(text: str) -> str:
    """Rewrite pipe tables into Telegram-friendly Markdown bullet groups."""
    if "|" not in text or "-" not in text:
        return text

    lines = text.split("\n")
    out: list[str] = []
    in_fence = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()

        if stripped.startswith("```"):
            in_fence = not in_fence
            out.append(line)
            i += 1
            continue
        if in_fence:
            out.append(line)
            i += 1
            continue

        if (
            "|" in line
            and i + 1 < len(lines)
            and _TABLE_SEPARATOR_RE.match(lines[i + 1])
        ):
            block = [line, lines[i + 1]]
            j = i + 2
            while j < len(lines) and _is_table_row(lines[j]):
                block.append(lines[j])
                j += 1
            out.append(_render_table_block(block))
            i = j
            continue

        out.append(line)
        i += 1

    return "\n".join(out)


def md_to_html(text: str) -> str:
    """Convert common Markdown to Telegram-compatible HTML.

    Handles: GFM tables (as bullet groups), **bold**, *italic*, `code`,
    ```code blocks```, # headings -> bold, and escapes <>& in the source first.
    """
    text = rewrite_gfm_tables(text)
    text = escape_html(text)
    text = re.sub(r"```(?:\w*\n)?([\s\S]*?)```", r"<pre>\1</pre>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
    return text


def strip_html_to_plain(html: str) -> str:
    """Strip Telegram HTML tags for plain-text fallback."""
    plain = re.sub(r"<[^>]+>", "", html)
    return plain.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


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


def prepare_telegram_chunks(
    text: str,
    message_format: str = "html",
    *,
    max_len: int = MAX_TG_MESSAGE_LEN,
) -> list[tuple[str, str | None]]:
    """Split *text* and return (chunk, parse_mode) pairs for send_message."""
    mode = normalize_message_format(message_format)
    body = text or "_(No response)_"
    plain_chunks = split_message(body, max_len=max_len)

    if mode == "plain":
        return [(chunk, None) for chunk in plain_chunks]

    return [(md_to_html(chunk), "HTML") for chunk in plain_chunks]
