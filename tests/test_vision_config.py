"""Vision config loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from best_buddy_agent.config import ConfigError, load_config
from tests.conftest import write_test_conf


def test_vision_disabled_by_default(tmp_path: Path):
    conf = write_test_conf(tmp_path)
    cfg = load_config(str(conf))
    assert cfg.vision.enabled is False


def test_vision_enabled(tmp_path: Path):
    conf = write_test_conf(tmp_path)
    conf.write_text(
        conf.read_text(encoding="utf-8")
        + """
[vision]
enabled = true
max_image_bytes = 5000000
""",
        encoding="utf-8",
    )
    cfg = load_config(str(conf))
    assert cfg.vision.enabled is True
    assert cfg.vision.max_image_bytes == 5_000_000
    assert cfg.vision.file_prefix == "tg_photo"


def test_vision_file_prefix(tmp_path: Path):
    conf = write_test_conf(tmp_path)
    conf.write_text(
        conf.read_text(encoding="utf-8")
        + """
[vision]
enabled = true
max_image_bytes = 10485760
file_prefix = bb_img
""",
        encoding="utf-8",
    )
    cfg = load_config(str(conf))
    assert cfg.vision.file_prefix == "bb_img"


def test_vision_max_bytes_invalid(tmp_path: Path):
    conf = write_test_conf(tmp_path)
    conf.write_text(
        conf.read_text(encoding="utf-8")
        + """
[vision]
enabled = true
max_image_bytes = huge
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="max_image_bytes"):
        load_config(str(conf))
