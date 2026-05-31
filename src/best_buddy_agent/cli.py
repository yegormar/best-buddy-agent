"""CLI entrypoint for interactive Best Buddy agent chat."""

from __future__ import annotations

import argparse
import sys

from .approval import cli_approval_resolver
from .agent_runtime import InterruptResult
from .config import load_config, ConfigError
from .runtime import chat_once
from .startup_check import format_startup_report, validate_startup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run best_buddy_agent chat loop with local Ollama")
    parser.add_argument("--config", default=None, help="Path to best_buddy_agent.conf")
    parser.add_argument("--thread-id", default="cli-main", help="Conversation thread ID")
    parser.add_argument("--timeout-sec", type=int, default=90, help="Per-call timeout in seconds")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
        results = validate_startup(cfg, profile="chat", conf_path=args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    name = cfg.assistant_name
    print(format_startup_report(results))
    print(f"{name} chat started. Type /exit to quit.")
    if cfg.log_enabled and cfg.log_file:
        print(f"Trace log (tail -f): {cfg.log_file}")
        if cfg.log_llm_wire:
            print("LLM wire logging on (LLM WIRE REQUEST/RESPONSE blocks in trace file).")
    elif not cfg.log_enabled:
        print(
            "Trace logging is off ([logging] enabled = false). "
            "Set enabled = true and file = ... in your config to trace turns.",
            file=sys.stderr,
        )
    pending: InterruptResult | None = None
    last_user_text = ""
    prefix = f"{cfg.assistant_name}>"

    while True:
        try:
            user = input("you> ").strip()
        except EOFError:
            print()
            break
        if not user:
            if pending:
                user = last_user_text
            else:
                continue
        if user in {"/exit", "/quit"}:
            break

        last_user_text = user

        try:
            if pending:
                reply = chat_once(
                    config=cfg,
                    thread_id=args.thread_id,
                    user_text=user,
                    timeout_sec=args.timeout_sec,
                    approval_resolver=cli_approval_resolver,
                    pending_interrupt=pending,
                    interrupt_approved=cli_approval_resolver(
                        {
                            "tool_name": pending.tool_name,
                            "args": pending.args,
                            "message": pending.message,
                        }
                    ),
                )
                pending = None
            else:
                reply = chat_once(
                    config=cfg,
                    thread_id=args.thread_id,
                    user_text=user,
                    timeout_sec=args.timeout_sec,
                    approval_resolver=cli_approval_resolver,
                )
        except Exception as exc:
            print(f"{prefix} error: {exc}", file=sys.stderr)
            continue

        if isinstance(reply, InterruptResult):
            pending = reply
            print(f"{prefix} [approval required] {reply.message}")
            print("  Re-send your last message (or any text) to approve/deny via prompt.")
            continue

        print(f"{prefix} {reply}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
