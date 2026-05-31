"""Run live system smoke tests (memory, Gmail, scheduling)."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Run Best Buddy live system smoke tests against your real config and data",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to best_buddy_agent.conf (or set BEST_BUDDY_AGENT_CONF)",
    )
    parser.add_argument(
        "-k",
        dest="keyword",
        default="",
        help="Pytest -k expression (e.g. memory or scheduling)",
    )
    parser.add_argument(
        "--no-ollama",
        action="store_true",
        help="Skip tests that need the LLM (runs scheduler-only checks)",
    )
    args, extra = parser.parse_known_args(argv)

    env = os.environ.copy()
    env["BEST_BUDDY_AGENT_SYSTEM_TEST"] = "1"
    if not args.no_ollama:
        env["BEST_BUDDY_AGENT_OLLAMA_TEST"] = "1"
    if args.config:
        env["BEST_BUDDY_AGENT_CONF"] = str(Path(args.config).expanduser().resolve())

    expectations = root / "tests" / "system" / "expectations.json"
    example = root / "tests" / "system" / "expectations.example.json"
    if not expectations.is_file():
        print(
            f"Missing {expectations}\n"
            f"Copy and edit:\n  cp {example} {expectations}",
            file=sys.stderr,
        )
        return 2

    cmd = [sys.executable, "-m", "pytest", "tests/system", "-v"]
    if args.keyword:
        cmd.extend(["-k", args.keyword])
    cmd.extend(extra)

    print("Running system smoke tests…")
    print(f"  config: {env.get('BEST_BUDDY_AGENT_CONF', root / 'conf' / 'best_buddy_agent.conf')}")
    print(f"  data:   {Path.home() / '.best_buddy_agent'}")
    print(f"  cmd:    {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=root, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
