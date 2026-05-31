from __future__ import annotations

from pathlib import Path

from best_buddy_agent.config import load_config
from tests.conftest import write_test_conf
from best_buddy_agent.tools import filesystem as fs
from best_buddy_agent.tools.memory_tools import search_memory


def _write_conf(tmp_path: Path) -> Path:
    return write_test_conf(tmp_path, system_prompt_override="sys")


def test_list_files_tool(tmp_path: Path):
    cfg = load_config(str(_write_conf(tmp_path)))
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    out = fs.list_files(cfg, pattern="*.txt")
    assert "a.txt" in out


def test_search_memory_tool():
    out = search_memory("family", top_k=3)
    assert isinstance(out, str)
