"""Serializable data models for inter-activity state in the V2 workflow.

All models are Pydantic BaseModel so they can be passed between Temporal
activities as JSON-serializable dicts via ``model_dump()`` / ``model_validate()``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class SpecParseResult(BaseModel):
    """Output of the spec parsing + PRA activity."""

    spec_content: str = ""
    validated_spec: str = ""
    requirements_title: str = ""
    plan_dir: str = ""
    context_files_count: int = 0
    pra_iterations: int = 0


class PlanResult(BaseModel):
    """Output of the planning activity."""

    adapter_result_dict: Dict[str, Any] = Field(default_factory=dict)
    spec_content_for_planning: str = ""
    requirements_title: str = ""


class ExecutionResult(BaseModel):
    """Output of the coding team execution activity."""

    completed_task_ids: List[str] = Field(default_factory=list)
    failed_tasks: List[Dict[str, Any]] = Field(default_factory=list)
    merged_count: int = 0
