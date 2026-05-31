"""
Agent Loop with pydantic-ai + Ollama
=====================================
Demonstrates:
  - How to wire Ollama as a backend via OllamaModel + OllamaProvider
  - Tool registration with @agent.tool
  - Structured output via a Pydantic model (output tool)
  - How to inspect the exact HTTP JSON sent to Ollama (/v1/chat/completions)
  - How that differs from pydantic-ai's internal ModelRequest/ModelResponse objects

Requires best-buddy-agent deps (from repo root):
    cd best-buddy-agent && .venv/bin/pip install -e .

Defaults match conf/best_buddy_agent.conf ([llm] section).
Override with env vars if needed:
    OLLAMA_BASE_URL=http://ubuntu-llm:11434/v1
    OLLAMA_MODEL=qwen3:14b
"""

import asyncio
import dataclasses
import json
import os
import sys
from dataclasses import dataclass

import httpx
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.capabilities import Thinking
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import RunContext

# Same host/model as conf/best_buddy_agent.conf unless overridden.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ubuntu-llm:11434/v1").rstrip("/")
if not OLLAMA_BASE_URL.endswith("/v1"):
    OLLAMA_BASE_URL = f"{OLLAMA_BASE_URL}/v1"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:26b")
# Set SHOW_PYDANTIC_MESSAGES=1 to also dump pydantic-ai's internal message objects.
SHOW_PYDANTIC_MESSAGES = os.getenv("SHOW_PYDANTIC_MESSAGES", "").lower() in ("1", "true", "yes")


def _format_wire_body(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return "(empty body)"
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        return raw


def create_stdout_wire_client() -> httpx.AsyncClient:
    """httpx client that prints exact /v1/chat/completions request/response bodies."""
    seq = 0

    async def on_request(request: httpx.Request) -> None:
        nonlocal seq
        url = str(request.url)
        if "/chat/completions" not in url:
            return
        seq += 1
        body = request.content.decode("utf-8") if request.content else ""
        print(f"\n{'─' * 60}")
        print(f"LLM WIRE REQUEST #{seq}  {request.method} {url}")
        print(f"{'─' * 60}")
        print(_format_wire_body(body))

    async def on_response(response: httpx.Response) -> None:
        url = str(response.request.url)
        if "/chat/completions" not in url:
            return
        await response.aread()
        print(f"\n{'─' * 60}")
        print(f"LLM WIRE RESPONSE #{seq}  HTTP {response.status_code} {url}")
        print(f"{'─' * 60}")
        print(_format_wire_body(response.text))

    return httpx.AsyncClient(
        event_hooks={"request": [on_request], "response": [on_response]},
        timeout=httpx.Timeout(120.0),
    )


def _check_ollama() -> None:
    """Fail fast with a readable message when Ollama is unreachable."""
    url = f"{OLLAMA_BASE_URL.removesuffix('/v1')}/v1/models"
    try:
        resp = httpx.get(url, timeout=5.0)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        print(
            f"Cannot reach Ollama at {OLLAMA_BASE_URL}\n"
            f"  ({exc})\n"
            "Set OLLAMA_BASE_URL if your server is elsewhere, e.g.:\n"
            "  export OLLAMA_BASE_URL=http://ubuntu-llm:11434/v1",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    models = {m["id"] for m in resp.json().get("data", [])}
    if OLLAMA_MODEL not in models:
        sample = ", ".join(sorted(models)[:5])
        print(
            f"Model {OLLAMA_MODEL!r} not found on {OLLAMA_BASE_URL}\n"
            f"  Available (sample): {sample}\n"
            f"Set OLLAMA_MODEL to one of the tags above.",
            file=sys.stderr,
        )
        raise SystemExit(1)


# ─────────────────────────────────────────────────────────────
# 1. MODEL — point pydantic-ai at your Ollama server
# ─────────────────────────────────────────────────────────────

_wire_client = create_stdout_wire_client()

model = OllamaModel(
    OLLAMA_MODEL,
    provider=OllamaProvider(base_url=OLLAMA_BASE_URL, http_client=_wire_client),
    settings={
        "temperature": 0.1,
        # Qwen3: disable reasoning blocks that break structured output parsing.
        "openai_reasoning_effort": "none",
    },
)


# ─────────────────────────────────────────────────────────────
# 2. DEPENDENCIES — context your tools need (e.g. a DB session)
#    pydantic-ai injects this into every tool call via RunContext
# ─────────────────────────────────────────────────────────────

@dataclass
class AppDeps:
    user_id: str          # e.g. could carry a DB connection, API key, etc.


# ─────────────────────────────────────────────────────────────
# 3. STRUCTURED OUTPUT — what the agent must return
#    With tools present, pydantic-ai uses an output tool (ToolOutput mode).
# ─────────────────────────────────────────────────────────────

class FinalAnswer(BaseModel):
    summary: str


# ─────────────────────────────────────────────────────────────
# 4. AGENT — the core object
# ─────────────────────────────────────────────────────────────

agent: Agent[AppDeps, FinalAnswer] = Agent(
    model=model,
    deps_type=AppDeps,
    output_type=FinalAnswer,
    instructions=(
        "You are a helpful assistant with access to weather and stock tools. "
        "Always call the relevant tools to get real data before answering. "
        "Never make up numbers. "
        "When done, call the final output tool with one summary string — do not reply in plain text."
    ),
    model_settings=ModelSettings(thinking=False),
    capabilities=[Thinking(effort=False)],
    retries=2,
)


# ─────────────────────────────────────────────────────────────
# 5. TOOLS — decorated functions pydantic-ai auto-registers
#
#    The decorator introspects the function signature and docstring
#    to build the JSON schema description sent to the model.
#    RunContext carries AppDeps; additional args become tool parameters.
# ─────────────────────────────────────────────────────────────

@agent.tool
async def get_weather(ctx: RunContext[AppDeps], city: str) -> dict:
    """Get current weather conditions for a city.

    Args:
        city: The city name, e.g. 'Ottawa' or 'Paris'.
    """
    print(f"  [TOOL] get_weather called for '{city}' by user '{ctx.deps.user_id}'")

    # In production: await httpx.get("https://api.weather.com/...") etc.
    fake_data = {
        "Ottawa": {"temp_c": 22, "condition": "Partly cloudy", "humidity": 58},
        "Paris":  {"temp_c": 18, "condition": "Rainy",         "humidity": 80},
        "Tokyo":  {"temp_c": 29, "condition": "Sunny",         "humidity": 70},
    }
    return fake_data.get(city, {"error": f"No weather data for '{city}'"})


@agent.tool
async def get_stock_price(ctx: RunContext[AppDeps], ticker: str) -> dict:
    """Get the current stock price for a ticker symbol.

    Args:
        ticker: Stock ticker symbol, e.g. 'AAPL', 'NVDA', 'TSLA'.
    """
    print(f"  [TOOL] get_stock_price called for '{ticker}' by user '{ctx.deps.user_id}'")

    fake_prices = {"AAPL": 213.45, "NVDA": 875.20, "TSLA": 182.10}
    price = fake_prices.get(ticker.upper())
    if price:
        return {"ticker": ticker.upper(), "price_usd": price, "currency": "USD"}
    return {"error": f"Unknown ticker: {ticker}"}


def _tools_called(messages) -> list[str]:
    names: list[str] = []
    for msg in messages:
        if not isinstance(msg, ModelResponse):
            continue
        for part in msg.parts:
            if isinstance(part, ToolCallPart) and part.tool_name:
                names.append(part.tool_name)
    return names


# ─────────────────────────────────────────────────────────────
# 6. RUN THE AGENT + INSPECT RAW MESSAGES
# ─────────────────────────────────────────────────────────────

async def main():
    _check_ollama()

    user_prompt = "What's the weather in Ottawa and Paris, and what's Apple's stock price?"

    print("=" * 60)
    print(f"USER: {user_prompt}")
    print(f"Ollama: {OLLAMA_BASE_URL}  model: {OLLAMA_MODEL}")
    print("=" * 60)

    deps = AppDeps(user_id="user-42")

    result = await agent.run(user_prompt, deps=deps)
    messages = result.all_messages()

    # ── Structured output (pydantic model, fully type-safe) ──
    print("\n── STRUCTURED OUTPUT ──")
    print(f"Summary: {result.output.summary}")

    tools = _tools_called(messages)
    print(f"Tools called: {tools}")

    # Wire bodies were printed live during agent.run() via httpx event hooks above.
    # Optionally dump pydantic-ai's internal representation (not what Ollama receives).
    if SHOW_PYDANTIC_MESSAGES:
        print("\n── PYDANTIC-AI INTERNAL MESSAGES (not the HTTP wire format) ──")
        for i, msg in enumerate(messages):
            print(f"\n[{i}] {type(msg).__name__}")
            payload = dataclasses.asdict(msg) if dataclasses.is_dataclass(msg) else msg.model_dump()
            print(json.dumps(payload, indent=2, default=str))

    await _wire_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
