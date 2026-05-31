"""Minimal structured-output call against Ollama (no user tools).

Disable thinking the pydantic-ai way:
  capabilities=[Thinking(effort=False)]

That maps to reasoning_effort='none' on Ollama /v1/chat/completions.

qwen3.5 + NativeOutput: reasoning_effort=none also disables response_format/json_schema
on Ollama, so this example uses ToolOutput for structured output with thinking off.
qwen3:14b can use NativeOutput(CitiesResponse) with the same Thinking(effort=False).
"""

import time

from pydantic import BaseModel
from pydantic_ai import Agent, ToolOutput
from pydantic_ai.capabilities import Thinking
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider


class City(BaseModel):
    name: str
    country: str


class CitiesResponse(BaseModel):
    cities: list[City]


model = OllamaModel(
    "granite4.1:3b",
    provider=OllamaProvider(base_url="http://ubuntu-llm:11434/v1"),
    settings={"temperature": 0.1},
)

agent: Agent[None, CitiesResponse] = Agent(
    model=model,
    output_type=ToolOutput(CitiesResponse),
    capabilities=[Thinking(effort=False)],
    retries=2,
)

started = time.perf_counter()
result = agent.run_sync("Name two capital cities in Europe.")
elapsed_s = time.perf_counter() - started

print(result.output)
print(f"Elapsed: {elapsed_s:.2f}s")
# CitiesResponse(cities=[City(name='Paris', country='France'), City(name='Berlin', country='Germany')])
