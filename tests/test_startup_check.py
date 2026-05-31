from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from best_buddy_agent.config import AgentConfig, GmailSettings, TelegramSettings
from best_buddy_agent.startup_check import (
    StartupError,
    run_startup_checks,
    validate_startup,
)
from tests.conftest import write_test_conf


def _minimal_config(tmp_path: Path, **kwargs) -> AgentConfig:
    conf = write_test_conf(tmp_path, system_prompt_override="test prompt")
    cfg = __import__("best_buddy_agent.config", fromlist=["load_config"]).load_config(str(conf))
    for key, val in kwargs.items():
        setattr(cfg, key, val)
    return cfg


def test_validate_startup_ollama_ok(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(tmp_path / "data"))
    cfg = _minimal_config(tmp_path)
    payload = json.dumps({"models": [{"name": cfg.llm_model}]}).encode()

    class FakeResp:
        def read(self):
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    with patch("urllib.request.urlopen", return_value=FakeResp()):
        results = validate_startup(cfg, profile="chat")
    names = {r.name for r in results}
    assert "ollama" in names
    assert all(r.ok for r in results)


def test_validate_startup_ollama_missing_model(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(tmp_path / "data"))
    cfg = _minimal_config(tmp_path)
    payload = json.dumps({"models": [{"name": "other:latest"}]}).encode()

    class FakeResp:
        def read(self):
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    with patch("urllib.request.urlopen", return_value=FakeResp()):
        with pytest.raises(StartupError) as exc:
            validate_startup(cfg, profile="chat")
    assert "ollama" in str(exc.value).lower() or "model" in str(exc.value).lower()


def test_gmail_enabled_without_credentials_fails(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(tmp_path / "data"))
    cfg = _minimal_config(tmp_path)
    cfg.gmail = GmailSettings(
        enabled=True,
        credentials_path=tmp_path / "missing_creds.json",
        token_path=tmp_path / "missing_token.json",
    )
    payload = json.dumps({"models": [{"name": cfg.llm_model}]}).encode()

    class FakeResp:
        def read(self):
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    with patch("urllib.request.urlopen", return_value=FakeResp()):
        with pytest.raises(StartupError) as exc:
            validate_startup(cfg, profile="chat")
    msg = str(exc.value)
    assert "gmail" in msg.lower()


def test_telegram_enabled_but_incomplete_fails(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(tmp_path / "data"))
    cfg = _minimal_config(tmp_path)
    payload = json.dumps({"models": [{"name": cfg.llm_model}]}).encode()

    class FakeResp:
        def read(self):
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    with patch("urllib.request.urlopen", return_value=FakeResp()):
        with patch(
            "best_buddy_agent.startup_check.load_telegram_settings",
            return_value=TelegramSettings(enabled=True, bot_token="", allowed_user_id=None),
        ):
            with pytest.raises(StartupError) as exc:
                validate_startup(cfg, profile="chat")
    assert "telegram" in str(exc.value).lower()
