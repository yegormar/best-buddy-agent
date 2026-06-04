import pytest

from best_buddy_agent.channels.telegram_format import (
    MAX_TG_MESSAGE_LEN,
    escape_html,
    md_to_html,
    normalize_message_format,
    prepare_telegram_chunks,
    rewrite_gfm_tables,
    split_message,
    strip_html_to_plain,
)


def test_split_short_unchanged():
    text = "hello"
    assert split_message(text) == ["hello"]


def test_split_long_message():
    text = "word " * 900
    chunks = split_message(text, max_len=100)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")


def test_max_len_constant():
    assert MAX_TG_MESSAGE_LEN == 4096


def test_normalize_message_format_defaults_html():
    assert normalize_message_format("") == "html"
    assert normalize_message_format("HTML") == "html"
    assert normalize_message_format("plain") == "plain"


def test_normalize_message_format_invalid():
    with pytest.raises(ValueError):
        normalize_message_format("markdown")


def test_escape_html():
    assert escape_html("5 > 3 && x < 10") == "5 &gt; 3 &amp;&amp; x &lt; 10"


def test_md_to_html_bold():
    assert md_to_html("Hello **world**") == "Hello <b>world</b>"


def test_md_to_html_italic():
    assert md_to_html("Hello *world*") == "Hello <i>world</i>"


def test_md_to_html_inline_code():
    assert md_to_html("Use `print()` here") == "Use <code>print()</code> here"


def test_md_to_html_fenced_code():
    result = md_to_html("```python\nprint('hi')\n```")
    assert "<pre>" in result
    assert "print('hi')" in result


def test_md_to_html_heading():
    assert md_to_html("# Main Title") == "<b>Main Title</b>"


def test_md_to_html_escapes_before_convert():
    assert "&lt;" in md_to_html("5 > 3 && x < 10")
    assert "<b>" not in md_to_html("5 > 3")


def test_strip_html_to_plain():
    html = "Hello <b>world</b> &amp; <code>x</code>"
    assert strip_html_to_plain(html) == "Hello world & x"


def test_prepare_telegram_chunks_plain():
    chunks = prepare_telegram_chunks("hello", "plain")
    assert chunks == [("hello", None)]


def test_prepare_telegram_chunks_html():
    chunks = prepare_telegram_chunks("**hi**", "html")
    assert chunks == [("<b>hi</b>", "HTML")]


def test_rewrite_gfm_tables_three_column():
    table = """| Parameter | Value | Status |
| :--- | :--- | :--- |
| Link | Stable | OK |
| Memory | Updated | Active |"""
    out = rewrite_gfm_tables(table)
    assert "|" not in out
    assert "**Link**" in out
    assert "• Value: Stable" in out
    assert "• Status: OK" in out
    assert "**Memory**" in out


def test_rewrite_gfm_tables_skips_fenced_code():
    text = "```\n| a | b |\n|---|---|\n```"
    assert rewrite_gfm_tables(text) == text


def test_md_to_html_converts_rewritten_table():
    table = "| A | B |\n| --- | --- |\n| x | y |"
    html = md_to_html(table)
    assert "<b>x</b>" in html
    assert "• B: y" in html
    assert "|" not in html


def test_prepare_telegram_chunks_splits_before_convert():
    long_bold = "**" + "word " * 900 + "**"
    chunks = prepare_telegram_chunks(long_bold, "html", max_len=100)
    assert len(chunks) > 1
    assert all(parse_mode == "HTML" for _, parse_mode in chunks)
    assert all(len(c) <= 100 for c, _ in chunks)
