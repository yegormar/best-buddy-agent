from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from best_buddy_agent import agent_trace
from best_buddy_agent.config import ConfigError, load_config
from tests.conftest import write_test_conf
from best_buddy_agent.llm_wire_logging import create_wire_logging_http_client


def test_wire_http_client_logs_request_and_response(trace_config, monkeypatch):
    logged: list[tuple[str, str]] = []

    def fake_trace(config, *, kind, seq, headline, body):
        logged.append((kind, body))

    monkeypatch.setattr(agent_trace, "trace_llm_wire_http", fake_trace)
    trace_config.log_llm_wire = True

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"id": "x", "object": "chat.completion", "choices": [{"message": {"content": "ok"}}]},
            request=request,
        )

    client = create_wire_logging_http_client(
        trace_config,
        transport=httpx.MockTransport(handler),
    )
    payload = {"model": "test", "messages": [{"role": "user", "content": "hi"}]}

    async def _run() -> None:
        await client.post("http://localhost:11434/v1/chat/completions", json=payload)
        await client.aclose()

    asyncio.run(_run())

    assert len(logged) == 2
    assert logged[0][0] == "REQUEST"
    assert logged[1][0] == "RESPONSE"
    req_body = json.loads(logged[0][1])
    assert req_body["messages"][0]["content"] == "hi"
    resp_body = json.loads(logged[1][1])
    assert resp_body["choices"][0]["message"]["content"] == "ok"


def test_log_llm_wire_requires_logging_enabled(tmp_path):
    conf = write_test_conf(
        tmp_path,
        system_prompt_override="sys",
        extra_logging="log_llm_wire = true",
    )
    with pytest.raises(ConfigError, match="log_llm_wire requires logging.enabled"):
        load_config(str(conf))


def test_load_config_log_llm_wire(tmp_path):
    conf = write_test_conf(
        tmp_path,
        system_prompt_override="sys",
        extra_logging="""
enabled = true
file = logs/trace.log
log_llm_wire = true
""",
    )
    cfg = load_config(str(conf))
    assert cfg.log_llm_wire is True


def test_wire_blocks_in_trace_file(trace_config, tmp_path):
    trace_config.log_llm_wire = True
    trace_config.log_file = tmp_path / "wire.log"

    import best_buddy_agent.trace_logging as tl

    tl._LOGGER_CACHE.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True}, request=request)

    client = create_wire_logging_http_client(
        trace_config,
        transport=httpx.MockTransport(handler),
    )
    asyncio.run(
        client.post(
            "http://127.0.0.1/v1/chat/completions",
            content=json.dumps({"model": "m", "messages": []}),
            headers={"Content-Type": "application/json"},
        )
    )
    asyncio.run(client.aclose())

    blocks = agent_trace.read_trace_blocks(trace_config.log_file)
    titles = [t for t, _ in blocks]
    assert "LLM WIRE REQUEST" in titles
    assert "LLM WIRE RESPONSE" in titles
