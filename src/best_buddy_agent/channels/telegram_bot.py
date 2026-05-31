"""CLI entrypoint for the Best Buddy Telegram channel."""

from __future__ import annotations

import argparse
import logging
import sys

from ..config import ConfigError, load_config, load_telegram_settings
from ..log_redaction import install_secret_redaction
from ..startup_check import format_startup_report, validate_startup
from .telegram import run_polling


def _check_telegram_dependency() -> None:
    try:
        import telegram  # noqa: F401
    except ImportError as exc:
        raise ConfigError(
            "python-telegram-bot is not installed. "
            'Install with: pip install -e ".[telegram]"'
        ) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Best Buddy Telegram bot (long polling)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to best_buddy_agent.conf",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        _check_telegram_dependency()
        cfg = load_config(args.config)
        tg = load_telegram_settings(args.config)
        install_secret_redaction(
            extra_literals=[tg.bot_token] if tg.bot_token else (),
        )
        results = validate_startup(cfg, profile="telegram", conf_path=args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    name = cfg.assistant_name
    print(format_startup_report(results))
    print(f"{name} Telegram bot starting (Ctrl+C to stop).")
    if cfg.log_enabled and cfg.log_file:
        print(f"Trace log (tail -f): {cfg.log_file}")

    try:
        run_polling(cfg, tg)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
