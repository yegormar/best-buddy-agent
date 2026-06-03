from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_extract_auth_code_bare():
    from best_buddy_agent.gmail_client import _extract_auth_code

    assert _extract_auth_code("abc123") == "abc123"


def test_extract_auth_code_from_redirect_url():
    from best_buddy_agent.gmail_client import _extract_auth_code

    url = "http://localhost:1/?code=4%2F0Abc&scope=email"
    assert _extract_auth_code(url) == "4/0Abc"


def test_extract_auth_code_empty_raises():
    from best_buddy_agent.gmail_client import GmailError, _extract_auth_code

    with pytest.raises(GmailError, match="empty"):
        _extract_auth_code("  ")


def test_ensure_oauth_redirect_uri_from_client_config():
    from best_buddy_agent.gmail_client import _ensure_oauth_redirect_uri

    class FakeFlow:
        client_config = {
            "installed": {"redirect_uris": ["http://localhost", "urn:ietf:wg:oauth:2.0:oob"]}
        }

    flow = FakeFlow()
    assert _ensure_oauth_redirect_uri(flow) == "http://localhost"
    assert flow.redirect_uri == "http://localhost"


def test_search_gmail_empty_results():
    from best_buddy_agent.gmail_client import search_messages

    service = MagicMock()
    service.users().messages().list().execute.return_value = {"messages": []}
    out = search_messages(service, "is:unread", max_results=5)
    assert "zero results" in out.lower()


def test_search_gmail_returns_json():
    from best_buddy_agent.gmail_client import search_messages

    service = MagicMock()
    list_chain = service.users().messages().list.return_value
    list_chain.execute.return_value = {"messages": [{"id": "m1", "threadId": "t1"}]}
    get_chain = service.users().messages().get.return_value
    get_chain.execute.return_value = {
        "id": "m1",
        "threadId": "t1",
        "snippet": "Hi",
        "labelIds": ["INBOX"],
        "payload": {
            "headers": [
                {"name": "From", "value": "a@b.com"},
                {"name": "Subject", "value": "Test"},
            ],
        },
    }
    out = search_messages(service, "is:unread", max_results=5)
    data = json.loads(out)
    assert len(data) == 1
    assert data[0]["id"] == "m1"


def test_create_draft_calls_drafts_api(tmp_path):
    from best_buddy_agent.gmail_client import create_draft

    service = MagicMock()
    draft_chain = service.users().drafts().create.return_value
    draft_chain.execute.return_value = {"id": "d123"}

    result = create_draft(
        service,
        message="Hello",
        to="user@example.com",
        subject="Subj",
        files_root=tmp_path,
    )
    assert "d123" in result
    service.users().drafts().create.assert_called_once()
    call_body = service.users().drafts().create.call_args[1]["body"]
    assert "message" in call_body
    assert "raw" in call_body["message"]


def test_gmail_disabled_raises(tmp_path):
    from configparser import ConfigParser

    from best_buddy_agent.config import AgentConfig, GmailSettings, _load_gmail_settings
    from best_buddy_agent.prompt_loader import load_prompt_catalog
    from best_buddy_agent.tools import gmail_tools as gt

    conf_dir = Path(__file__).resolve().parents[1] / "conf"
    prompts = load_prompt_catalog(conf_dir=conf_dir, language="en")
    parser = ConfigParser()
    parser.read_dict({"gmail": {"enabled": "false"}})
    gmail = _load_gmail_settings(parser, conf_dir / "best_buddy_agent.conf.example")

    cfg = AgentConfig(
        llm_host="h",
        llm_port=1,
        llm_model="m",
        llm_keep_alive="5m",
        llm_temperature=0.7,
        llm_top_p=0.9,
        llm_num_ctx=8192,
        llm_think=False,
        prompt_language="en",
        prompts=prompts,
        files_root=tmp_path,
        max_tool_iterations=4,
        gmail=gmail,
    )
    with pytest.raises(gt.ToolError, match="disabled"):
        gt.search_gmail(cfg, "is:unread")


def test_load_gmail_config_section():
    from configparser import ConfigParser

    from best_buddy_agent.config import _load_gmail_settings

    conf_file = Path(__file__).resolve().parents[1] / "conf" / "best_buddy_agent.conf.example"
    parser = ConfigParser()
    parser.read(conf_file, encoding="utf-8")
    gmail = _load_gmail_settings(parser, conf_file)
    assert gmail.enabled is False
    assert "gmail" in str(gmail.credentials_path)
