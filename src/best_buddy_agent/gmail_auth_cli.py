"""CLI: one-time Gmail OAuth for Best Buddy."""

from __future__ import annotations

import argparse
import sys

from .config import ConfigError, load_config
from . import gmail_client as gc
from .tools import gmail_tools as gt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Authenticate Best Buddy with Gmail (read + drafts only; no send tool)",
    )
    parser.add_argument("--config", default=None, help="Path to best_buddy_agent.conf")
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print Gmail config/token status and exit",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Headless: print OAuth URL and paste authorization code (no local browser)",
    )
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    if args.status:
        print(gt.gmail_status(cfg))
        return 0

    if not cfg.gmail.enabled:
        print(
            "Gmail is disabled. Set [gmail] enabled = true in your config, then retry.",
            file=sys.stderr,
        )
        return 2

    if not gc.has_credentials(cfg.gmail.credentials_path):
        print(
            f"Missing OAuth client secrets at:\n  {cfg.gmail.credentials_path}\n\n"
            "Create a Google Cloud OAuth Desktop client, enable Gmail API, download\n"
            "credentials.json to that path. See docs/GMAIL.md.",
            file=sys.stderr,
        )
        return 2

    try:
        tp = gc.run_oauth_flow(
            credentials=cfg.gmail.credentials_path,
            token=cfg.gmail.token_path,
            no_browser=args.no_browser,
        )
    except gc.GmailError as exc:
        print(f"OAuth failed: {exc}", file=sys.stderr)
        return 1

    status, detail = gc.check_token_health(tp)
    print(f"Gmail authenticated. Token saved to:\n  {tp}")
    print(f"Health: {status} — {detail}")
    print("\nScopes: read inbox + create drafts (Best Buddy has no send-email tool).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
