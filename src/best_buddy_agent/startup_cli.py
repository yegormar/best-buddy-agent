"""CLI: run startup health checks without starting chat."""

from __future__ import annotations

import argparse
import sys

from .config import ConfigError, load_config
from .startup_check import format_startup_report, run_startup_checks, validate_startup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate Best Buddy config, LLM, Gmail, Telegram, and data paths",
    )
    parser.add_argument("--config", default=None, help="Path to best_buddy_agent.conf")
    parser.add_argument(
        "--profile",
        choices=("chat", "telegram", "all"),
        default="all",
        help="chat: CLI session; telegram: bot; all: every enabled integration",
    )
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    try:
        results = validate_startup(cfg, profile=args.profile, conf_path=args.config)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(format_startup_report(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
