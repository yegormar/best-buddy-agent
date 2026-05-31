"""CLI to authenticate Google Calendar OAuth for Best Buddy."""

from __future__ import annotations

import argparse
import sys

from .calendar_client import check_token_health, run_oauth_flow, token_path
from .config import ConfigError, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Authenticate Best Buddy Google Calendar OAuth")
    parser.add_argument("--config", default=None, help="Path to best_buddy_agent.conf")
    parser.add_argument("--status", action="store_true", help="Check token health only")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    cal = cfg.calendar
    tp = cal.token_path

    if args.status:
        status, detail = check_token_health(tp)
        print(f"Calendar token: {status} — {detail}")
        print(f"Path: {tp}")
        return 0 if status in {"valid", "refreshed"} else 1

    if not cal.credentials_path.is_file():
        print(f"Missing credentials.json: {cal.credentials_path}", file=sys.stderr)
        print("Use the same Desktop OAuth JSON as Gmail (Google Cloud Console).", file=sys.stderr)
        return 2

    print("Opening browser for Calendar OAuth consent…")
    written = run_oauth_flow(credentials=cal.credentials_path, token=tp)
    print(f"Calendar token saved: {written}")
    status, detail = check_token_health(written)
    print(f"Health: {status} — {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
