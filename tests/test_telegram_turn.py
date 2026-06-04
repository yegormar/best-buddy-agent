import time
from unittest.mock import patch

from best_buddy_agent.agent_runtime import InterruptResult
from best_buddy_agent.channels import telegram as tg
from best_buddy_agent.config import AgentConfig, TelegramSettings


def _minimal_config() -> AgentConfig:
    from pathlib import Path

    from best_buddy_agent.config import load_config

    root = Path(__file__).resolve().parents[1]
    example = root / "conf" / "best_buddy_agent.conf.example"
    local = root / "conf" / "best_buddy_agent.conf"
    path = local if local.is_file() else example
    return load_config(str(path))


def test_format_interrupt_includes_tool():
    intr = InterruptResult(
        tool_name="delete_memory",
        tool_call_id="call-1",
        args={"memory_id": "abc"},
        message="Delete this memory?",
    )
    text = tg.format_interrupt(intr)
    assert "delete_memory" in text
    assert "Delete this memory?" in text


def test_pending_lifecycle():
    chat_id = 999001
    tg.clear_pending(chat_id)
    assert not tg.has_pending(chat_id)

    cfg = _minimal_config()
    intr = InterruptResult(tool_name="write_file", tool_call_id="c1", args={})
    tg._pending_by_chat[chat_id] = tg.PendingApproval(
        interrupt=intr,
        thread_id="telegram:dm:999001",
        last_user_text="write file",
        config=cfg,
        created_at=time.time(),
    )
    assert tg.has_pending(chat_id)
    tg.clear_pending(chat_id)
    assert not tg.has_pending(chat_id)


def test_run_turn_sync_returns_text():
    cfg = _minimal_config()
    with patch("best_buddy_agent.channels.telegram.chat_once", return_value="hi there"):
        out = tg.run_turn_sync(cfg, "telegram:dm:1", "hello")
    assert out == "hi there"


def test_run_turn_sync_interrupt():
    cfg = _minimal_config()
    intr = InterruptResult(tool_name="delete_memory", tool_call_id="x", args={})
    with patch("best_buddy_agent.channels.telegram.chat_once", return_value=intr):
        out = tg.run_turn_sync(cfg, "telegram:dm:1", "delete x")
    assert isinstance(out, InterruptResult)


def test_load_telegram_settings_from_env(monkeypatch):
    from best_buddy_agent.config import load_telegram_settings

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", "4242")
    monkeypatch.setenv("TELEGRAM_ENABLED", "true")
    settings = load_telegram_settings()
    assert settings.bot_token == "tok123"
    assert settings.allowed_user_id == 4242
    assert settings.enabled is True
    assert settings.message_format == "html"


def test_format_interrupt_plain_mode():
    intr = InterruptResult(
        tool_name="delete_memory",
        tool_call_id="call-1",
        args={"memory_id": "abc"},
        message="Delete this memory?",
    )
    text = tg.format_interrupt(intr, message_format="plain")
    assert "Delete this memory?" in text
    assert "**" not in text


def test_validate_telegram_startup_errors():
    from best_buddy_agent.config import ConfigError, validate_telegram_startup

    try:
        validate_telegram_startup(TelegramSettings())
        assert False, "expected ConfigError"
    except ConfigError:
        pass
