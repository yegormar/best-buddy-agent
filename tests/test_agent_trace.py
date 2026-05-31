from __future__ import annotations

from best_buddy_agent import agent_trace
from best_buddy_agent.trace_logging import trace_block


def test_trace_block_writes_parsable_blocks(trace_config, tmp_path):
    trace_block(trace_config, "TEST BLOCK", "line one\nline two")
    assert trace_config.log_file is not None
    blocks = agent_trace.read_trace_blocks(trace_config.log_file)
    assert len(blocks) == 1
    title, body = blocks[0]
    assert title == "TEST BLOCK"
    assert "line one" in body
    assert "line two" in body


def test_trace_redacts_prompts_when_disabled(tmp_path):
    from best_buddy_agent.config import load_config
    from tests.conftest import write_test_conf

    conf = write_test_conf(
        tmp_path,
        system_prompt_override="sys",
        extra_logging="""
enabled = true
file = logs/trace.log
log_prompts = false
log_responses = true
""",
    )
    cfg = load_config(str(conf))
    secret = "super-secret-instructions"
    agent_trace.trace_instructions(cfg, secret)
    blocks = agent_trace.read_trace_blocks(cfg.log_file)
    assert blocks
    _title, body = blocks[-1]
    assert secret not in body
    assert "redacted" in body
