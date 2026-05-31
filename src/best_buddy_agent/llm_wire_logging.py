"""Log exact HTTP bodies sent to / received from the LLM (Ollama OpenAI-compatible API)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
from pydantic_ai.models import DEFAULT_HTTP_TIMEOUT

if TYPE_CHECKING:
    from .config import AgentConfig


def _format_wire_body(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return "(empty body)"
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        return raw


def _is_chat_completions(url: str) -> bool:
    return "/chat/completions" in url


def create_wire_logging_http_client(
    config: AgentConfig,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """httpx client that writes LLM WIRE REQUEST/RESPONSE blocks to the trace log."""
    from .agent_trace import trace_llm_wire_http

    seq = 0

    async def on_request(request: httpx.Request) -> None:
        nonlocal seq
        url = str(request.url)
        if not _is_chat_completions(url):
            return
        seq += 1
        n = seq
        body = request.content.decode("utf-8") if request.content else ""
        trace_llm_wire_http(
            config,
            kind="REQUEST",
            seq=n,
            headline=f"{request.method} {url}",
            body=_format_wire_body(body),
        )

    async def on_response(response: httpx.Response) -> None:
        url = str(response.request.url)
        if not _is_chat_completions(url):
            return
        await response.aread()
        body = response.text
        trace_llm_wire_http(
            config,
            kind="RESPONSE",
            seq=seq,
            headline=f"HTTP {response.status_code} {url}",
            body=_format_wire_body(body),
        )

    kwargs: dict = {
        "event_hooks": {"request": [on_request], "response": [on_response]},
        "timeout": httpx.Timeout(float(DEFAULT_HTTP_TIMEOUT)),
    }
    if transport is not None:
        kwargs["transport"] = transport
    return httpx.AsyncClient(**kwargs)
