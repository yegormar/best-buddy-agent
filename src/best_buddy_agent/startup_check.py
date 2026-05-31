"""Startup validation — fail fast before chat or Telegram serves traffic."""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import AgentConfig, ConfigError, TelegramSettings, load_telegram_settings


class StartupError(ConfigError):
    """One or more startup checks failed."""


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def _data_dir() -> Path:
    return Path(
        os.environ.get("BEST_BUDDY_AGENT_DATA_DIR", Path.home() / ".best_buddy_agent")
    ).expanduser().resolve()


def _check_data_directory() -> CheckResult:
    data = _data_dir()
    try:
        data.mkdir(parents=True, exist_ok=True)
        probe = data / ".startup_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return CheckResult("data_directory", True, str(data))
    except OSError as exc:
        return CheckResult("data_directory", False, f"{data}: {exc}")


def _check_sqlite_db(name: str, filename: str) -> CheckResult:
    path = _data_dir() / filename
    try:
        conn = sqlite3.connect(path, timeout=5)
        conn.execute("SELECT 1")
        conn.close()
        return CheckResult(name, True, str(path))
    except sqlite3.Error as exc:
        return CheckResult(name, False, f"{path}: {exc}")


def _check_logging(config: AgentConfig) -> CheckResult:
    if not config.log_enabled or config.log_file is None:
        return CheckResult("logging", True, "disabled")
    path = config.log_file
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8"):
            pass
        return CheckResult("logging", True, str(path))
    except OSError as exc:
        return CheckResult("logging", False, f"{path}: {exc}")


def _check_files_root(config: AgentConfig) -> CheckResult:
    root = config.files_root
    if root.is_dir():
        return CheckResult("files_root", True, str(root))
    return CheckResult("files_root", False, f"not a directory: {root}")


def _check_ollama(config: AgentConfig, *, timeout_sec: float = 8.0) -> CheckResult:
    url = f"{config.ollama_base_url.rstrip('/')}/api/tags"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return CheckResult(
            "ollama",
            False,
            f"HTTP {exc.code} from {url}",
        )
    except urllib.error.URLError as exc:
        return CheckResult(
            "ollama",
            False,
            f"cannot reach {config.llm_host}:{config.llm_port} — {exc.reason}",
        )
    except (TimeoutError, json.JSONDecodeError) as exc:
        return CheckResult("ollama", False, f"{url}: {exc}")

    models = payload.get("models") or []
    names = {str(m.get("name", "")) for m in models if m.get("name")}
    wanted = config.llm_model.strip()
    if wanted in names:
        return CheckResult("ollama", True, f"{wanted} available at {config.ollama_base_url}")

    # Ollama may report names with/without tags (e.g. qwen3:14b vs qwen3:14b-instruct)
    base = wanted.split(":")[0] if ":" in wanted else wanted
    related = [n for n in names if n == wanted or n.startswith(f"{wanted}:") or n.startswith(f"{base}:")]
    if related:
        return CheckResult(
            "ollama",
            True,
            f"model {wanted!r} not exact match; found {related[0]!r} at {config.ollama_base_url}",
        )
    sample = ", ".join(sorted(names)[:8])
    more = "" if len(names) <= 8 else f" (+{len(names) - 8} more)"
    return CheckResult(
        "ollama",
        False,
        f"model {wanted!r} not found on server. Installed: {sample}{more}",
    )


def _check_gmail_deps() -> CheckResult:
    try:
        import googleapiclient.discovery  # noqa: F401
        import google_auth_oauthlib  # noqa: F401

        return CheckResult("gmail_packages", True, "google-api-python-client installed")
    except ImportError:
        return CheckResult(
            "gmail_packages",
            False,
            'install Gmail support: pip install -e ".[gmail]"',
        )


def _check_gmail(config: AgentConfig) -> list[CheckResult]:
    g = config.gmail
    if not g.enabled:
        return [CheckResult("gmail", True, "disabled in config")]

    results: list[CheckResult] = [_check_gmail_deps()]
    creds = g.credentials_path
    if not creds.is_file():
        results.append(
            CheckResult(
                "gmail_credentials",
                False,
                f"missing {creds} — download OAuth Desktop JSON from Google Cloud",
            )
        )
    else:
        results.append(CheckResult("gmail_credentials", True, str(creds)))

    token = g.token_path
    if not token.is_file():
        results.append(
            CheckResult(
                "gmail_token",
                False,
                f"missing {token} — run: best-buddy-agent-gmail-auth --config <conf>",
            )
        )
    else:
        from . import gmail_client as gc

        status, detail = gc.check_token_health(token)
        ok = status in ("valid", "refreshed")
        results.append(CheckResult("gmail_token", ok, f"{status}: {detail}"))

    ready = g.is_ready() and all(r.ok for r in results)
    if not ready:
        results.append(
            CheckResult(
                "gmail",
                False,
                "enabled but not ready (see gmail_* checks above)",
            )
        )
    else:
        results.append(CheckResult("gmail", True, "read + draft tools will load"))
    return results


def _check_calendar(config: AgentConfig) -> list[CheckResult]:
    cal = config.calendar
    if not cal.enabled:
        return [CheckResult("calendar", True, "disabled")]
    results: list[CheckResult] = []
    if not cal.credentials_path.is_file():
        results.append(CheckResult("calendar_credentials", False, f"missing {cal.credentials_path}"))
    else:
        results.append(CheckResult("calendar_credentials", True, str(cal.credentials_path)))
    if not cal.token_path.is_file():
        results.append(
            CheckResult(
                "calendar_token",
                False,
                f"missing {cal.token_path} — run best-buddy-agent-calendar-auth",
            )
        )
    else:
        from . import calendar_client as cc

        status, detail = cc.check_token_health(cal.token_path)
        ok = status in ("valid", "refreshed")
        results.append(CheckResult("calendar_token", ok, f"{status}: {detail}"))
    ok = cal.is_ready() and all(r.ok for r in results)
    results.append(
        CheckResult(
            "calendar",
            ok,
            "ready" if ok else "enabled but not ready",
        )
    )
    return results


def _check_deadline_watch(
    config: AgentConfig,
    *,
    profile: str,
    conf_path: str | Path | None = None,
) -> list[CheckResult]:
    dw = config.deadline_watch
    if not dw.enabled:
        return [CheckResult("deadline_watch", True, "disabled")]
    results: list[CheckResult] = []
    if not config.gmail.is_ready():
        results.append(
            CheckResult(
                "deadline_watch_gmail",
                False,
                "Gmail must be configured for inbox scanning",
            )
        )
    else:
        results.append(CheckResult("deadline_watch_gmail", True, "Gmail ready"))
    if profile in ("telegram", "all"):
        tg = load_telegram_settings(str(conf_path) if conf_path else None)
        if not tg.is_configured():
            results.append(
                CheckResult(
                    "deadline_watch_telegram",
                    False,
                    "Telegram required for proactive deadline proposals",
                )
            )
        else:
            results.append(CheckResult("deadline_watch_telegram", True, "Telegram configured"))
    else:
        results.append(
            CheckResult(
                "deadline_watch_telegram",
                True,
                "run best-buddy-agent-telegram for proactive notifications",
            )
        )
    ok = all(r.ok for r in results)
    results.append(
        CheckResult(
            "deadline_watch",
            ok,
            "ready" if ok else "enabled but not fully ready",
        )
    )
    return results


def _check_reliability(config: AgentConfig) -> CheckResult:
    if not config.reliability_required:
        return CheckResult("reliability", True, "not required")
    try:
        from pydantic_deep import PatchToolCallsCapability  # noqa: F401
        from pydantic_ai_summarization import create_summarization_processor  # noqa: F401

        return CheckResult("reliability", True, "optional reliability packages OK")
    except ImportError as exc:
        return CheckResult(
            "reliability",
            False,
            f"agent.reliability_required=true but packages missing: {exc}",
        )


def _check_telegram(settings: TelegramSettings) -> list[CheckResult]:
    if not settings.enabled:
        return [CheckResult("telegram", True, "disabled in config")]

    results: list[CheckResult] = []
    try:
        import telegram  # noqa: F401

        results.append(CheckResult("telegram_package", True, "python-telegram-bot installed"))
    except ImportError:
        results.append(
            CheckResult(
                "telegram_package",
                False,
                'install: pip install -e ".[telegram]"',
            )
        )

    if not settings.bot_token:
        results.append(
            CheckResult(
                "telegram_token",
                False,
                "set TELEGRAM_BOT_TOKEN or [telegram] bot_token",
            )
        )
    else:
        results.append(CheckResult("telegram_token", True, "bot token set"))

    if settings.allowed_user_id is None:
        results.append(
            CheckResult(
                "telegram_user",
                False,
                "set TELEGRAM_ALLOWED_USER_ID or [telegram] allowed_user_id",
            )
        )
    else:
        results.append(
            CheckResult("telegram_user", True, f"allowed_user_id={settings.allowed_user_id}")
        )

    ok = all(r.ok for r in results)
    results.append(
        CheckResult(
            "telegram",
            ok,
            "ready" if ok else "enabled but not ready",
        )
    )
    return results


def _check_memory_index() -> CheckResult:
    index = _data_dir() / "memory_vectors" / "index.faiss"
    if not index.exists():
        return CheckResult("memory_index", True, "no FAISS index yet (will build on use)")
    try:
        import faiss  # noqa: F401

        return CheckResult("memory_index", True, str(index))
    except ImportError:
        return CheckResult(
            "memory_index",
            False,
            "memory_vectors/index.faiss exists but faiss not installed — pip install -e '.[faiss]'",
        )


def run_startup_checks(
    config: AgentConfig,
    *,
    profile: str = "chat",
    conf_path: str | Path | None = None,
    ollama_timeout_sec: float = 8.0,
) -> list[CheckResult]:
    """Run checks for *profile*: ``chat``, ``telegram``, or ``all``."""
    profile = (profile or "chat").strip().lower()
    results: list[CheckResult] = [
        _check_data_directory(),
        _check_files_root(config),
        _check_sqlite_db("memory_db", "memory.db"),
        _check_sqlite_db("threads_db", "threads.db"),
        _check_sqlite_db("workflows_db", "workflows.db"),
        _check_logging(config),
        _check_ollama(config, timeout_sec=ollama_timeout_sec),
        _check_memory_index(),
        _check_reliability(config),
    ]
    results.extend(_check_gmail(config))
    results.extend(_check_calendar(config))
    results.extend(_check_deadline_watch(config, profile=profile, conf_path=conf_path))

    if profile in ("telegram", "all"):
        tg = load_telegram_settings(conf_path)
        results.extend(_check_telegram(tg))
    elif profile == "chat":
        tg = load_telegram_settings(conf_path)
        if tg.enabled:
            results.extend(_check_telegram(tg))

    return results


def validate_startup(
    config: AgentConfig,
    *,
    profile: str = "chat",
    conf_path: str | Path | None = None,
    ollama_timeout_sec: float = 8.0,
) -> list[CheckResult]:
    """Run startup checks; raise StartupError if any failed."""
    results = run_startup_checks(
        config,
        profile=profile,
        conf_path=conf_path,
        ollama_timeout_sec=ollama_timeout_sec,
    )
    failed = [r for r in results if not r.ok]
    if failed:
        lines = [f"  - {r.name}: {r.detail}" for r in failed]
        raise StartupError(
            "Startup checks failed:\n" + "\n".join(lines)
        )
    return results


def format_startup_report(results: list[CheckResult]) -> str:
    lines = ["Startup checks:"]
    for r in results:
        mark = "OK" if r.ok else "FAIL"
        lines.append(f"  [{mark}] {r.name}: {r.detail}")
    return "\n".join(lines)
