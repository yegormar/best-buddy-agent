"""STT config and device resolution tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from best_buddy_agent.config import ConfigError, load_config
from best_buddy_agent.transcription.startup import resolve_effective_device
from best_buddy_agent.transcription.service import reset_stt_for_tests
from tests.conftest import write_test_conf


def test_stt_disabled_when_section_missing(tmp_path: Path):
    conf = write_test_conf(tmp_path)
    cfg = load_config(str(conf))
    assert cfg.stt.enabled is False


def test_stt_enabled_requires_keys(tmp_path: Path):
    conf = write_test_conf(
        tmp_path,
        extra_llm="",
    )
    text = conf.read_text(encoding="utf-8")
    conf.write_text(
        text
        + """
[stt]
enabled = true
device = auto
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"\[stt\] requires"):
        load_config(str(conf))


def test_stt_enabled_loads_full_section(tmp_path: Path):
    hf = tmp_path / "hf"
    cache = hf / "cache"
    cache.mkdir(parents=True)
    conf = write_test_conf(tmp_path)
    conf.write_text(
        conf.read_text(encoding="utf-8")
        + f"""
[stt]
enabled = true
device = auto
model = large-v3
compute_type_cpu = int8
compute_type_cuda = float16
beam_size = 10
temperature = 0.1
best_of = 5
patience = 2
condition_on_previous_text = true
vad_filter = true
vad_min_silence_duration_ms = 200
hf_home = {hf}
hf_hub_cache = {cache}
echo_transcript = true
""",
        encoding="utf-8",
    )
    cfg = load_config(str(conf))
    assert cfg.stt.enabled is True
    assert cfg.stt.device == "auto"
    assert cfg.stt.beam_size == 10
    assert cfg.stt.transcribe_kwargs()["vad_filter"] is True


def test_resolve_effective_device_auto_cpu(monkeypatch):
    class FakeCt2:
        @staticmethod
        def get_cuda_device_count():
            return 0

    monkeypatch.setitem(
        __import__("sys").modules,
        "ctranslate2",
        FakeCt2,
    )
    assert resolve_effective_device("auto") == "cpu"
    assert resolve_effective_device("cpu") == "cpu"


def test_resolve_effective_device_auto_cuda(monkeypatch):
    class FakeCt2:
        @staticmethod
        def get_cuda_device_count():
            return 1

    monkeypatch.setitem(
        __import__("sys").modules,
        "ctranslate2",
        FakeCt2,
    )
    assert resolve_effective_device("auto") == "cuda"


@pytest.fixture(autouse=True)
def _reset_stt():
    reset_stt_for_tests()
    yield
    reset_stt_for_tests()
