"""
DevOps tool agent for planning-v2.

Participates in phases: Planning, Implementation.
Focuses on CI/CD pipelines, infrastructure, and deployment planning.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ...models import ToolAgentPhaseInput, ToolAgentPhaseOutput
from ..json_utils import parse_json_with_recovery, default_decompose_by_sections

if TYPE_CHECKING:
    from shared.llm import LLMClient

logger = logging.getLogger(__name__)


def _merge_devops_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge devops results from multiple chunks."""
    merged: Dict[str, Any] = {
        "pipeline_stages": [],
        "infrastructure": {},
        "deployment_strategy": "",
        "monitoring": [],
        "security": [],
        "recommendations": [],
        "summary": "",
    }
    strategies = []
    summaries = []

    for r in results:
        if isinstance(r.get("pipeline_stages"), list):
            for stage in r["pipeline_stages"]:
                if stage not in merged["pipeline_stages"]:
                    merged["pipeline_stages"].append(stage)
        if isinstance(r.get("infrastructure"), dict):
            merged["infrastructure"].update(r["infrastructure"])
        if r.get("deployment_strategy"):
            strategies.append(str(r["deployment_strategy"]))
        if isinstance(r.get("monitoring"), list):
            merged["monitoring"].extend(r["monitoring"])
        if isinstance(r.get("security"), list):
            merged["security"].extend(r["security"])
        if isinstance(r.get("recommendations"), list):
            merged["recommendations"].extend(r["recommendations"])
        if r.get("summary"):
            summaries.append(str(r["summary"]))

    merged["deployment_strategy"] = strategies[0] if strategies else ""
    merged["summary"] = f"Merged {len(results)} sections. " + " ".join(summaries[:2])
    return merged

DEVOPS_PLANNING_PROMPT = """You are a DevOps expert. Create a DevOps plan for:

Specification:
---
{spec_content}
---

Plan summary from spec review: {plan_summary}

Plan for:
1. CI/CD pipeline stages
2. Infrastructure requirements
3. Deployment strategy
4. Monitoring and observability
5. Security considerations

Respond with JSON:
{{
  "pipeline_stages": ["build", "test", "deploy"],
  "infrastructure": {{"compute": "...", "database": "...", "networking": "..."}},
  "deployment_strategy": "blue-green|rolling|canary",
  "monitoring": ["metrics", "logs", "traces"],
  "security": ["secrets management", "network policies"],
  "recommendations": ["devops recommendations"],
  "summary": "brief summary"
}}
"""

DEVOPS_PLANNING_CHUNK_PROMPT = """You are a DevOps expert. Analyze this SECTION of a specification for DevOps:

SECTION:
---
{chunk_content}
---

Respond with concise JSON for THIS section only:
{{
  "pipeline_stages": ["relevant stages"],
  "infrastructure": {{"relevant": "requirements"}},
  "deployment_strategy": "strategy if applicable",
  "monitoring": ["monitoring needs"],
  "security": ["security considerations"],
  "recommendations": ["devops recommendations"],
  "summary": "brief summary"
}}
"""


class DevOpsToolAgent:
    """
    DevOps tool agent: CI/CD pipelines, infrastructure, deployment planning.
    
    Participates in Planning and Implementation phases per the matrix.
    """

    def __init__(self, llm: Optional["LLMClient"] = None) -> None:
        self.llm = llm

    def plan(self, inp: ToolAgentPhaseInput) -> ToolAgentPhaseOutput:
        """Planning phase: create DevOps plan."""
        if not self.llm:
            return ToolAgentPhaseOutput(
                summary="DevOps planning skipped (no LLM).",
                recommendations=["Define CI/CD pipeline", "Plan infrastructure"],
            )
        
        plan_summary = ""
        if inp.spec_review_result:
            plan_summary = getattr(inp.spec_review_result, "plan_summary", "") or ""

        spec_content = inp.spec_content or ""
        prompt = DEVOPS_PLANNING_PROMPT.format(
            spec_content=spec_content[:6000],
            plan_summary=plan_summary[:2000],
        )
        data = parse_json_with_recovery(
            self.llm,
            prompt,
            agent_name="DevOps",
            decompose_fn=default_decompose_by_sections,
            merge_fn=_merge_devops_results,
            original_content=spec_content,
            chunk_prompt_template=DEVOPS_PLANNING_CHUNK_PROMPT,
        )
        
        recommendations = data.get("recommendations") or []
        if not isinstance(recommendations, list):
            recommendations = [str(recommendations)]
        
        return ToolAgentPhaseOutput(
            summary=data.get("summary", "DevOps planning complete."),
            recommendations=recommendations,
            metadata={
                "pipeline_stages": data.get("pipeline_stages", []),
                "infrastructure": data.get("infrastructure", {}),
                "deployment_strategy": data.get("deployment_strategy", ""),
                "monitoring": data.get("monitoring", []),
                "security": data.get("security", []),
            },
        )

    def execute(self, inp: ToolAgentPhaseInput) -> ToolAgentPhaseOutput:
        """Implementation phase: generate DevOps artifacts."""
        pipeline_stages = inp.metadata.get("pipeline_stages", [])
        infrastructure = inp.metadata.get("infrastructure", {})
        deployment_strategy = inp.metadata.get("deployment_strategy", "")
        monitoring = inp.metadata.get("monitoring", [])
        security = inp.metadata.get("security", [])
        
        content_parts = ["# DevOps Plan\n\n"]
        
        if pipeline_stages:
            content_parts.append("## CI/CD Pipeline Stages\n")
            for i, stage in enumerate(pipeline_stages, 1):
                content_parts.append(f"{i}. {stage}\n")
            content_parts.append("\n")
        
        if infrastructure:
            content_parts.append("## Infrastructure\n")
            for key, value in infrastructure.items():
                content_parts.append(f"- **{key}:** {value}\n")
            content_parts.append("\n")
        
        if deployment_strategy:
            content_parts.append(f"## Deployment Strategy\n{deployment_strategy}\n\n")
        
        if monitoring:
            content_parts.append("## Monitoring\n")
            for item in monitoring:
                content_parts.append(f"- {item}\n")
            content_parts.append("\n")
        
        if security:
            content_parts.append("## Security\n")
            for item in security:
                content_parts.append(f"- {item}\n")
            content_parts.append("\n")
        
        files = {}
        if pipeline_stages or infrastructure:
            files["plan/devops.md"] = "".join(content_parts)
        
        return ToolAgentPhaseOutput(
            summary="DevOps artifacts generated.",
            files=files,
        )

    def review(self, inp: ToolAgentPhaseInput) -> ToolAgentPhaseOutput:
        """Review phase: DevOps does not participate."""
        return ToolAgentPhaseOutput(summary="DevOps review not applicable (per matrix).")

    def problem_solve(self, inp: ToolAgentPhaseInput) -> ToolAgentPhaseOutput:
        """Problem-solving phase: DevOps does not participate."""
        return ToolAgentPhaseOutput(summary="DevOps problem_solve not applicable (per matrix).")

    def deliver(self, inp: ToolAgentPhaseInput) -> ToolAgentPhaseOutput:
        """Deliver phase: DevOps does not participate."""
        return ToolAgentPhaseOutput(summary="DevOps deliver not applicable (per matrix).")
