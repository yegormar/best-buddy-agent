"""Structured outputs for workflow NL creation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WorkflowStepSpec(BaseModel):
    id: str = ""
    type: str = "prompt"
    prompt: str = ""
    message: str = ""
    operator: str = ""
    left: str = ""
    value: str = ""
    if_true: str = ""
    if_false: str = ""
    workflow_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = self.model_dump(exclude_none=True)
        return {k: v for k, v in data.items() if v != "" or k in {"id", "type"}}


class WorkflowPlan(BaseModel):
    name: str = Field(description="Short workflow name")
    schedule: dict[str, Any] | None = None
    steps: list[WorkflowStepSpec] = Field(min_length=1)
