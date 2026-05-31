from __future__ import annotations

import logging

from best_buddy_agent.log_redaction import (
    SecretRedactionFilter,
    install_secret_redaction,
    redact_secrets,
)


def test_redact_telegram_bot_url():
    raw = (
        "HTTP Request: POST "
        "https://api.telegram.org/bot123456:ABCdefGHI/getMe HTTP/1.1 200 OK"
    )
    out = redact_secrets(raw)
    assert "123456:ABCdefGHI" not in out
    assert "https://api.telegram.org/bot***REDACTED***/getMe" in out


def test_redact_known_literal():
    token = "8949365508:AAEozCow0VgNVT3LUk6qDkgzPOmgLDICFk4"
    out = redact_secrets(f"token={token}", extra_literals=[token])
    assert token not in out
    assert "***REDACTED***" in out


def test_filter_on_log_record():
    filt = SecretRedactionFilter()
    record = logging.LogRecord(
        name="httpx",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="POST https://api.telegram.org/bot99:SECRET/getUpdates",
        args=(),
        exc_info=None,
    )
    assert filt.filter(record) is True
    assert "SECRET" not in record.msg
    assert "***REDACTED***" in record.msg


def test_install_sets_httpx_warning():
    install_secret_redaction()
    assert logging.getLogger("httpx").level >= logging.WARNING
