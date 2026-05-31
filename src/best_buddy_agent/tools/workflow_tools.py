"""Workflow inspection tools."""

from __future__ import annotations

import json

from .. import workflow_engine as wf


class ToolError(Exception):
    """Raised when a workflow tool fails."""


def workflow_run_status(run_id: str) -> str:
    if not run_id.strip():
        raise ToolError("run_id is required")
    state = wf.get_run_state(run_id.strip())
    if state:
        return json.dumps(state, ensure_ascii=False, default=str)
    row = wf.get_workflow(run_id.strip())
    if row:
        runs = wf.get_run_history(run_id.strip())
        if runs:
            return json.dumps(runs[0], ensure_ascii=False, default=str)
    raise ToolError(f"No run or workflow found for id: {run_id}")
