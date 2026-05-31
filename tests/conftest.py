import ast
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_TEST_DATA_DIR = tempfile.mkdtemp(prefix="best-buddy-agent-tests-")
os.environ["BEST_BUDDY_AGENT_DATA_DIR"] = _TEST_DATA_DIR


def copy_prompt_bundle(dest_conf_dir: Path, *, language: str = "en") -> Path:
    """Copy bundled prompts into a temp conf directory for tests."""
    src = ROOT / "conf" / "prompts" / language
    dst = dest_conf_dir / "prompts" / language
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return dst


def write_test_conf(
    tmp_path: Path,
    *,
    system_prompt_override: str | None = "system prompt for tests",
    language: str = "en",
    llm_num_ctx: str = "8192",
    extra_llm: str = "",
    extra_logging: str = "",
) -> Path:
    copy_prompt_bundle(tmp_path, language=language)
    override_line = ""
    if system_prompt_override is not None:
        prompt = tmp_path / "prompt.txt"
        prompt.write_text(system_prompt_override, encoding="utf-8")
        override_line = "agent_system_prompt_file = prompt.txt"
    llm_block = f"""
llm_host = localhost
llm_port = 11434
llm_model = llama3:latest
llm_keep_alive = 5m
llm_temperature = 0.7
llm_top_p = 0.9
llm_num_ctx = {llm_num_ctx}
{override_line}
{extra_llm}""".strip()

    logging_block = extra_logging.strip() if extra_logging.strip() else "enabled = false"
    if "file = logs/" in logging_block:
        (tmp_path / "logs").mkdir(exist_ok=True)
    conf = tmp_path / "agent.conf"
    conf.write_text(
        f"""
[llm]
{llm_block}

[prompts]
language = {language}

[tools]
files_root = .
max_tool_iterations = 4

[logging]
{logging_block}
""".strip(),
        encoding="utf-8",
    )
    return conf


def load_test_config(tmp_path: Path, **write_kwargs):
    from best_buddy_agent.config import load_config

    conf = write_test_conf(tmp_path, **write_kwargs)
    return load_config(str(conf))


@pytest.fixture
def agent_config(tmp_path: Path):
    return load_test_config(tmp_path)


@pytest.fixture
def trace_config(tmp_path: Path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    return load_test_config(
        tmp_path,
        extra_logging="""
file = logs/agent-trace.log
log_prompts = true
log_responses = true
log_message_history = true
log_tool_args = true
enabled = true
""",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "ollama: live Ollama integration (set BEST_BUDDY_AGENT_OLLAMA_TEST=1)",
    )


def pytest_collection_modifyitems(config, items):
    if os.environ.get("BEST_BUDDY_AGENT_OLLAMA_TEST") == "1":
        return
    skip = pytest.mark.skip(reason="set BEST_BUDDY_AGENT_OLLAMA_TEST=1 to run live Ollama tests")
    for item in items:
        if "ollama" in item.keywords:
            item.add_marker(skip)
