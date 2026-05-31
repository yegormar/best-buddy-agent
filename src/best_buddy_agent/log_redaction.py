"""Redact secrets from log messages (Telegram bot token in httpx URLs, etc.)."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence

# https://api.telegram.org/bot<token>/method
_TELEGRAM_BOT_URL = re.compile(
    r"(https://api\.telegram\.org/bot)[^/\s\"']+",
    re.IGNORECASE,
)
# /bot<token>/method (relative URLs in some loggers)
_TELEGRAM_BOT_PATH = re.compile(r"(/bot)\d+:[A-Za-z0-9_-]+")


def redact_secrets(text: str, *, extra_literals: Sequence[str] = ()) -> str:
    """Mask Telegram bot tokens and other known secret literals."""
    if not text:
        return text
    out = _TELEGRAM_BOT_URL.sub(r"\1***REDACTED***", text)
    out = _TELEGRAM_BOT_PATH.sub(r"\1***REDACTED***", out)
    for literal in extra_literals:
        s = (literal or "").strip()
        if len(s) >= 12:
            out = out.replace(s, "***REDACTED***")
    return out


class SecretRedactionFilter(logging.Filter):
    """Apply :func:`redact_secrets` to every log record message."""

    def __init__(self, *, extra_literals: Sequence[str] = ()) -> None:
        super().__init__()
        self._extra_literals = tuple(extra_literals)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        redacted = redact_secrets(msg, extra_literals=self._extra_literals)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


def install_secret_redaction(*, extra_literals: Sequence[str] = ()) -> SecretRedactionFilter:
    """Attach redaction to root handlers and quiet noisy HTTP client loggers."""
    filt = SecretRedactionFilter(extra_literals=extra_literals)
    root = logging.getLogger()
    root.addFilter(filt)
    for handler in root.handlers:
        handler.addFilter(filt)
    # httpx logs full request URLs at INFO (includes bot token).
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    return filt
