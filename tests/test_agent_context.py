def test_context_redaction_and_memory_block():
    from best_buddy_agent import memory
    from best_buddy_agent.agent_context import redact_data_uris, build_memory_context

    raw = "data:image/png;base64," + ("A" * 300)
    redacted = redact_data_uris(raw)
    assert "stripped" in redacted

    memory.save_memory("fact", "User", "User enjoys storytelling")
    # Query aligned with saved subject (no list_entities flood fallback).
    block = build_memory_context(["User storytelling"])
    assert "User" in block
