"""Memory recall smoke tests against real ~/.best_buddy_agent/memory.db."""

from __future__ import annotations

import pytest

from .helpers import (
    extract_first_number,
    load_expectations,
    response_contains,
    response_contains_any,
    run_chat,
)

pytestmark = [pytest.mark.system, pytest.mark.ollama]


def test_memory_age(system_config, expectations, system_thread_id):
    mem = expectations.get("memory") or {}
    question = mem.get("age_question") or "How old am I?"
    expected = str(mem.get("expected_age") or "").strip()
    if not expected or expected == "CHANGE_ME":
        pytest.skip("Set memory.expected_age in tests/system/expectations.json")

    reply = run_chat(system_config, question, thread_id=system_thread_id)

    if expected.isdigit():
        found = extract_first_number(reply)
        assert found == expected, f"Expected age {expected}, got {found!r} in:\n{reply}"
    else:
        assert response_contains(reply, expected), f"Expected {expected!r} in:\n{reply}"


def test_memory_known_facts(system_config, expectations, system_thread_id):
    mem = expectations.get("memory") or {}
    question = mem.get("facts_question") or "What do you know about me?"
    must = [str(x).strip() for x in (mem.get("must_contain") or []) if str(x).strip()]
    must = [m for m in must if m != "CHANGE_ME"]
    if not must:
        pytest.skip("Set memory.must_contain in tests/system/expectations.json")

    reply = run_chat(system_config, question, thread_id=f"{system_thread_id}-facts")
    missing = response_contains_any(reply, must)
    assert not missing, f"Response missing expected facts {missing}:\n{reply}"
