from __future__ import annotations

from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models.test import TestModel

from best_buddy_agent.agent_runtime import _run_agent_sync, build_agent, run_turn
from best_buddy_agent.runtime import chat_once
from best_buddy_agent.threads import thread_conversation_rows


def _count_user_prompts(messages: list) -> int:
    n = 0
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for p in msg.parts:
                if isinstance(p, UserPromptPart):
                    n += 1
    return n


def test_run_sync_gets_one_user_message(agent_config):
    agent = build_agent(
        agent_config,
        model=TestModel(call_tools=[], custom_output_text="ok"),
        use_reliability=False,
    )
    _run_agent_sync(
        agent,
        config=agent_config,
        thread_id="wire-thread",
        user_text="one line only",
        workflow_context=None,
        approval_resolver=None,
        message_history=None,
        deferred_tool_results=None,
    )
    from best_buddy_agent.threads import load_thread_message_history

    history = load_thread_message_history("wire-thread")
    assert _count_user_prompts(history) >= 1


def test_chat_once_persists_canonical_history(agent_config, tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(data))

    agent = build_agent(
        agent_config,
        model=TestModel(call_tools=[], custom_output_text="reply"),
        use_reliability=False,
    )

    def _run(config, thread_id, user_text, **kwargs):
        return run_turn(config, thread_id, user_text, _agent=agent, **kwargs)

    monkeypatch.setattr("best_buddy_agent.runtime.run_turn", _run)
    chat_once(config=agent_config, thread_id="chat-dup", user_text="hi there")
    rows = thread_conversation_rows("chat-dup")
    assert any(r["role"] == "user" and "hi there" in r["content"] for r in rows)
    assert any(r["role"] == "assistant" for r in rows)
