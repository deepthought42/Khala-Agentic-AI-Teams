"""
Models for the Agent Builder Team.

Pipeline phases:
  DEFINING                   - ProcessAnalystAgent generates flowchart from user description
  AWAITING_FLOWCHART_APPROVAL - Human reviews the generated flowchart
  PLANNING                   - AgentPlannerAgent maps flowchart to agent specs
  AWAITING_PLAN_APPROVAL      - Human reviews the agent plan
  BUILDING                   - AgentBuilderAgent generates the team code
  REFINING                   - AgentRefinerAgent reviews and refines generated code
  DELIVERED                  - Final team code is ready for the user
  FAILED                     - Pipeline error
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class BuilderPhase(str, Enum):
    DEFINING = "defining"
    AWAITING_FLOWCHART_APPROVAL = "awaiting_flowchart_approval"
    PLANNING = "planning"
    AWAITING_PLAN_APPROVAL = "awaiting_plan_approval"
    BUILDING = "building"
    REFINING = "refining"
    DELIVERED = "delivered"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Flowchart models
# ---------------------------------------------------------------------------


class FlowchartNode(BaseModel):
    id: str = Field(description="Short unique identifier, e.g. 'n1', 'decision_review'.")
    label: str = Field(description="Human-readable node label.")
    node_type: str = Field(description="One of: start | process | decision | end.")


class FlowchartEdge(BaseModel):
    from_node: str
    to_node: str
    label: str = Field("", description="Edge condition label, e.g. 'Yes' / 'No'.")


class ProcessFlowchart(BaseModel):
    """Structured flowchart with Mermaid source."""

    nodes: List[FlowchartNode] = Field(default_factory=list)
    edges: List[FlowchartEdge] = Field(default_factory=list)
    mermaid: str = Field("", description="Mermaid flowchart TD source.")
    clarifying_questions: List[str] = Field(
        default_factory=list,
        description="Questions the process analyst needs answered to finalise the flowchart.",
    )
    validation_notes: List[str] = Field(default_factory=list)
    is_complete: bool = Field(True, description="True when all paths terminate at an end node.")


# ---------------------------------------------------------------------------
# Agent plan models
# ---------------------------------------------------------------------------


class AgentSpec(BaseModel):
    name: str = Field(description="PascalCase agent class name, e.g. 'ReviewerAgent'.")
    role: str = Field(description="Human-readable role title.")
    inputs: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(default_factory=list)
    description: str = Field(description="What this agent does and which flowchart nodes it handles.")
    flowchart_nodes: List[str] = Field(default_factory=list, description="Node IDs covered by this agent.")


class AgentPlan(BaseModel):
    team_name: str = Field(description="snake_case team module name, e.g. 'my_approval_team'.")
    pipeline_description: str
    phases: List[str] = Field(description="Ordered human-readable pipeline phase names.")
    human_checkpoints: List[str] = Field(default_factory=list)
    agents: List[AgentSpec]
    review_notes: str = ""


# ---------------------------------------------------------------------------
# Code delivery models
# ---------------------------------------------------------------------------


class GeneratedFile(BaseModel):
    filename: str = Field(description="Relative path from team root, e.g. 'models.py' or 'api/main.py'.")
    content: str
    description: str = ""


# ---------------------------------------------------------------------------
# Job model
# ---------------------------------------------------------------------------


class BuildJob(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    phase: BuilderPhase = BuilderPhase.DEFINING

    # Input
    process_description: str

    # Flowchart phase
    flowchart: Optional[ProcessFlowchart] = None
    flowchart_feedback: str = ""

    # Planning phase
    agent_plan: Optional[AgentPlan] = None
    plan_feedback: str = ""

    # Build + refine phase
    generated_files: List[GeneratedFile] = Field(default_factory=list)
    refinement_notes: str = ""

    # Delivery
    delivery_notes: str = ""

    # Error / metadata
    error: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())

    def touch(self) -> None:
        self.updated_at = datetime.now(tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# API request/response models
# ---------------------------------------------------------------------------


class StartBuildRequest(BaseModel):
    """POST /agent-builder/jobs — start a new build."""

    process_description: str = Field(
        ...,
        min_length=20,
        max_length=50_000,
        description="Describe the process you want to automate with an agent team.",
    )


class ApproveFlowchartRequest(BaseModel):
    """PUT /agent-builder/jobs/{job_id}/approve-flowchart."""

    approved: bool = Field(description="True to proceed to planning; False to request revision.")
    feedback: str = Field("", description="Optional feedback or changes to apply before proceeding.")


class ApprovePlanRequest(BaseModel):
    """PUT /agent-builder/jobs/{job_id}/approve-plan."""

    approved: bool = Field(description="True to proceed to building; False to request revision.")
    feedback: str = Field("", description="Optional feedback or changes to apply before building.")


class JobStatusResponse(BaseModel):
    """GET /agent-builder/jobs/{job_id}."""

    job_id: str
    phase: BuilderPhase
    process_description: str
    flowchart: Optional[ProcessFlowchart] = None
    agent_plan: Optional[AgentPlan] = None
    generated_files: List[Dict[str, str]] = Field(default_factory=list)
    delivery_notes: str = ""
    error: str = ""
    created_at: str
    updated_at: str
