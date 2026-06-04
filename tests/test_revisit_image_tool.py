"""revisit_image tool."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from best_buddy_agent.config import load_config
from best_buddy_agent.tools import vision_tools
from best_buddy_agent.vision_cache import cache_user_image
from tests.conftest import write_test_conf


def test_revisit_image_loads_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BEST_BUDDY_AGENT_DATA_DIR", str(tmp_path))
    conf = write_test_conf(tmp_path)
    conf.write_text(
        conf.read_text(encoding="utf-8")
        + """
[vision]
enabled = true
file_prefix = tg_photo
""",
        encoding="utf-8",
    )
    config = load_config(str(conf))
    filename, _ = cache_user_image(b"\xff\xd8\xff", prefix="tg_photo")

    mock_result = MagicMock()
    mock_result.output = "A red circle on white background."

    with patch("best_buddy_agent.tools.vision_tools.Agent") as agent_cls:
        agent_cls.return_value.run_sync.return_value = mock_result
        out = vision_tools.revisit_image(
            config, filename, "What shape do you see?"
        )

    assert "red circle" in out
    agent_cls.return_value.run_sync.assert_called_once()
