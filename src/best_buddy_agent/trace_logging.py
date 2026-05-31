"""Config-driven trace logging helpers for best_buddy_agent."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from .config import AgentConfig

_LOGGER_CACHE: dict[Path, logging.Logger] = {}
_CACHE_LOCK = threading.Lock()


def _get_trace_logger(config: AgentConfig) -> logging.Logger | None:
    if not config.log_enabled or not config.log_file:
        return None

    path = config.log_file
    with _CACHE_LOCK:
        cached = _LOGGER_CACHE.get(path)
        if cached is not None:
            return cached

        logger = logging.getLogger(f"best_buddy_agent.trace.{path}")
        logger.setLevel(logging.INFO)
        logger.propagate = False

        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

        _LOGGER_CACHE[path] = logger
        return logger


def trace_block(config: AgentConfig, title: str, body: str) -> None:
    """Write a single easy-to-copy trace block to the configured file."""
    logger = _get_trace_logger(config)
    if logger is None:
        return

    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    block = (
        f"\n===== {ts} | {title} =====\n"
        f"{body.rstrip()}\n"
        "===== END =====\n"
    )
    logger.info(block)
    for handler in logger.handlers:
        handler.flush()
