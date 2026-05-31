from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from best_buddy_agent import agent_runtime
from best_buddy_agent.agent_runtime import build_agent
from best_buddy_agent.config import ConfigError, WebSettings, load_config
from best_buddy_agent.tools import web_tools
from pydantic_ai.models.test import TestModel
from tests.conftest import write_test_conf


def _web_settings(**kwargs) -> WebSettings:
    return WebSettings(**kwargs)


def test_web_search_empty_query():
    with pytest.raises(web_tools.ToolError, match="query is required"):
        web_tools.web_search(_web_settings(), "")


def test_web_search_formats_results():
    hits = [
        {"title": "Example", "body": "Snippet text", "href": "https://example.com/a"},
        {"title": "Other", "snippet": "More info", "url": "https://example.com/b"},
    ]

    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def text(self, query, max_results=8):
            yield from hits

    with patch.dict("sys.modules", {"ddgs": MagicMock(DDGS=FakeDDGS)}):
        out = web_tools.web_search(_web_settings(), "test query", max_results=2)

    assert "[Result 1] Example" in out
    assert "SOURCE_URL: https://example.com/a" in out
    assert "[Result 2] Other" in out
    assert "SOURCE_URL: https://example.com/b" in out


def test_web_search_no_results():
    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def text(self, query, max_results=8):
            return iter([])

    with patch.dict("sys.modules", {"ddgs": MagicMock(DDGS=FakeDDGS)}):
        out = web_tools.web_search(_web_settings(), "nothing")

    assert out == "No results found for: nothing"


def test_fetch_url_rejects_private_host(monkeypatch):
    monkeypatch.setattr(
        web_tools.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 0))],
    )
    with pytest.raises(web_tools.ToolError, match="blocked address"):
        web_tools.fetch_url(_web_settings(), "http://127.0.0.1/")


def test_fetch_url_rejects_file_scheme():
    with pytest.raises(web_tools.ToolError, match="http:// or https://"):
        web_tools.fetch_url(_web_settings(), "file:///etc/passwd")


def test_fetch_url_rejects_metadata_hostname():
    with pytest.raises(web_tools.ToolError, match="not allowed"):
        web_tools.fetch_url(_web_settings(), "http://metadata.google.internal/")


def test_fetch_url_extracts_html_and_truncates():
    html = "<html><body><script>ignore</script><p>Hello world</p></body></html>"
    response = MagicMock()
    response.headers = {"content-type": "text/html"}
    response.text = html
    response.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=response):
        out = web_tools.fetch_url(_web_settings(max_fetch_chars=10), "https://example.com/page")

    assert out.startswith("SOURCE_URL: https://example.com/page")
    assert "Hello worl" in out
    assert "[Truncated:" in out


def test_load_config_web_section(tmp_path: Path):
    conf = write_test_conf(
        tmp_path,
        extra_web="enabled = true\nmax_results = 5\nmax_fetch_chars = 5000\ntimeout_seconds = 10",
    )
    cfg = load_config(str(conf))
    assert cfg.web.enabled is True
    assert cfg.web.max_results == 5
    assert cfg.web.max_fetch_chars == 5000
    assert cfg.web.timeout_seconds == 10


def test_load_config_web_invalid_max_results(tmp_path: Path):
    conf = write_test_conf(tmp_path, extra_web="enabled = true\nmax_results = 99")
    with pytest.raises(ConfigError, match="max_results"):
        load_config(str(conf))


def test_web_tool_prompts_load(tmp_path: Path):
    conf = write_test_conf(tmp_path, extra_web="enabled = true")
    cfg = load_config(str(conf))
    assert "DuckDuckGo" in cfg.prompts.get("tools/web_search")
    assert "http://" in cfg.prompts.get("tools/fetch_url")


def test_build_agent_registers_web_tools(tmp_path: Path):
    conf = write_test_conf(tmp_path, extra_web="enabled = true")
    cfg = load_config(str(conf))
    build_agent(cfg, model=TestModel(), use_reliability=False)
    names = {name for name, _ in agent_runtime.AGENT_TOOL_CATALOG}
    assert "web_search" in names
    assert "fetch_url" in names
