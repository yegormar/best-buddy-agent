from __future__ import annotations

from pathlib import Path

from best_buddy_agent.config import ConfigError, load_config
from best_buddy_agent.model_factory import build_ollama_model, build_thinking_capabilities
from tests.conftest import write_test_conf


def test_load_config_success(tmp_path: Path):
    conf = write_test_conf(
        tmp_path,
        system_prompt_override="hello prompt",
        llm_num_ctx="16K",
    )
    cfg = load_config(str(conf))
    assert cfg.llm_host == "localhost"
    assert cfg.llm_port == 11434
    assert cfg.llm_model == "llama3:latest"
    assert cfg.llm_num_ctx == 16384
    assert "hello prompt" in cfg.agent_system_prompt
    assert cfg.prompt_language == "en"
    assert cfg.log_enabled is False
    assert cfg.llm_think is True


def test_load_config_llm_think_false(tmp_path: Path):
    conf = write_test_conf(tmp_path, system_prompt_override="hello")
    text = conf.read_text(encoding="utf-8")
    if "llm_think" not in text:
        text = text.replace("llm_num_ctx = 8192", "llm_num_ctx = 8192\nllm_think = false")
        conf.write_text(text, encoding="utf-8")
    cfg = load_config(str(conf))
    assert cfg.llm_think is False


def test_ollama_model_disables_think_when_configured(agent_config):
    from pydantic_ai.capabilities import Thinking

    agent_config.llm_think = False
    agent_config.llm_model = "qwen3:14b"
    model = build_ollama_model(agent_config)
    assert model.settings.get("openai_reasoning_effort") == "none"
    caps = build_thinking_capabilities(agent_config)
    assert len(caps) == 1
    assert isinstance(caps[0], Thinking)
    assert caps[0].effort is False


def test_ollama_qwen35_skips_reasoning_effort_none(agent_config):
    from pydantic_ai.capabilities import Thinking

    agent_config.llm_think = False
    agent_config.llm_model = "qwen3.5:27b"
    model = build_ollama_model(agent_config)
    assert "openai_reasoning_effort" not in model.settings
    caps = build_thinking_capabilities(agent_config)
    assert caps[0].effort is False


def test_load_config_missing_required(tmp_path: Path):
    conf = tmp_path / "bad.conf"
    conf.write_text("[llm]\nllm_model=llama3:latest\n", encoding="utf-8")
    try:
        load_config(str(conf))
        assert False, "expected ConfigError"
    except ConfigError as exc:
        assert "Missing required" in str(exc)


def test_load_config_logging_section(tmp_path: Path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    conf = write_test_conf(
        tmp_path,
        system_prompt_override="hello prompt",
        extra_logging="""
enabled = true
file = logs/trace.log
log_prompts = false
""",
    )
    cfg = load_config(str(conf))
    assert cfg.log_enabled is True
    assert cfg.log_file == (log_dir / "trace.log").resolve()
    assert cfg.log_prompts is False
