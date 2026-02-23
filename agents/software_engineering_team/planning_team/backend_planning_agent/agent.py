"""Backend Planning agent: produces backend-specific PlanningGraph slice."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from planning_team.planning_graph import (
    EdgeType,
    PlanningDomain,
    PlanningEdge,
    PlanningGraph,
    PlanningNode,
    PlanningNodeKind,
    ensure_dict,
    ensure_str_list,
)
from planning_team.planning_template import parse_planning_template
from shared.llm import LLMClient
from shared.models import ProductRequirements, SystemArchitecture

from .models import BackendPlanningInput, BackendPlanningOutput
from .prompts import BACKEND_PLANNING_PROMPT

logger = logging.getLogger(__name__)


def _is_frontend_task(node: Dict[str, Any]) -> bool:
    """Return True if node clearly describes frontend work (should be skipped by backend planner)."""
    nid = (node.get("id") or "").lower()
    summary = (node.get("summary") or "").lower()
    details = (node.get("details") or "").lower()
    combined = f"{nid} {summary} {details}"
    # Node ID explicitly frontend
    if nid.startswith("frontend-"):
        return True
    # Clear frontend indicators in content (avoid matching backend terms like "api component")
    frontend_phrases = [
        "angular app",
        "angular frontend",
        "react app",
        "vue app",
        "frontend app",
        "initialize frontend",
        "frontend initialization",
        "frontend app shell",
        "app shell",
        "app-shell",
        "ui component",
        "frontend component",
        "mat-table",
        "mat-form",
        "mat-button",
        "angular routing",
    ]
    for phrase in frontend_phrases:
        if phrase in combined:
            return True
    return False


def _parse_graph_from_llm_output(data: Dict[str, Any]) -> PlanningGraph:
    """Parse LLM JSON output into PlanningGraph. Skips nodes that clearly belong to frontend."""
    graph = PlanningGraph()
    for n in data.get("nodes") or []:
        if not isinstance(n, dict) or not n.get("id"):
            continue
        if _is_frontend_task(n):
            logger.warning(
                "Backend Planning: skipping frontend task %s (summary: %s) - belongs to Frontend planner",
                n.get("id"),
                (n.get("summary") or "")[:60],
            )
            continue
        kind_str = (n.get("kind") or "task").lower()
        try:
            kind = PlanningNodeKind(kind_str)
        except ValueError:
            kind = PlanningNodeKind.STORY
        domain_str = (n.get("domain") or "backend").lower()
        try:
            domain = PlanningDomain(domain_str)
        except ValueError:
            domain = PlanningDomain.BACKEND
        # Only allow backend, git_setup, devops from backend planner; force others to backend
        if domain not in (PlanningDomain.BACKEND, PlanningDomain.GIT_SETUP, PlanningDomain.DEVOPS):
            domain = PlanningDomain.BACKEND
        meta = ensure_dict(n.get("metadata"))
        user_story = (n.get("user_story") or meta.get("user_story") or "").strip()
        if user_story:
            meta["user_story"] = user_story
        node = PlanningNode(
            id=n["id"],
            domain=domain,
            kind=kind,
            summary=n.get("summary", ""),
            details=n.get("details", ""),
            inputs=ensure_str_list(n.get("inputs")),
            outputs=ensure_str_list(n.get("outputs")),
            acceptance_criteria=ensure_str_list(n.get("acceptance_criteria")),
            parent_id=n.get("parent_id"),
            metadata=meta,
        )
        graph.add_node(node)
    for e in data.get("edges") or []:
        if not isinstance(e, dict) or not e.get("from_id") or not e.get("to_id"):
            continue
        type_str = (e.get("type") or "blocks").lower()
        try:
            edge_type = EdgeType(type_str)
        except ValueError:
            edge_type = EdgeType.BLOCKS
        graph.add_edge(PlanningEdge(from_id=e["from_id"], to_id=e["to_id"], type=edge_type))
    return graph


class BackendPlanningAgent:
    """Produces backend-specific PlanningGraph from requirements and architecture."""

    def __init__(self, llm_client: LLMClient) -> None:
        assert llm_client is not None, "llm_client is required"
        self.llm = llm_client

    def run(self, input_data: BackendPlanningInput) -> BackendPlanningOutput:
        """Generate backend planning graph."""
        logger.info("Backend Planning: starting for %s", input_data.requirements.title)
        reqs = input_data.requirements
        arch = input_data.architecture

        context_parts = [
            f"**Product Title:** {reqs.title}",
            f"**Description:** {reqs.description}",
            "**Acceptance Criteria:**",
            *[f"- {c}" for c in reqs.acceptance_criteria],
            "**Constraints:**",
            *[f"- {c}" for c in reqs.constraints],
        ]
        if input_data.project_overview:
            po = input_data.project_overview
            context_parts.extend([
                "",
                "**Project Overview:**",
                f"- Primary goal: {po.get('primary_goal', '')}",
                f"- Delivery strategy: {po.get('delivery_strategy', '')}",
            ])
        if arch:
            context_parts.extend([
                "",
                "**Architecture:**",
                arch.overview,
                "",
                "**Components (backend-relevant):**",
                *[f"- {c.name} ({c.type}): {c.description}" for c in arch.components if c.type in ("backend", "database", "api", "api_gateway")],
            ])
            if getattr(arch, "planning_hints", None):
                backend_hints = (arch.planning_hints or {}).get("backend") or {}
                hint_components = backend_hints.get("components") or []
                if hint_components:
                    context_parts.extend(
                        [
                            "",
                            "**Backend planning hints (from architecture):**",
                            "- Components to anchor tasks to: " + ", ".join(hint_components),
                        ]
                    )
        if input_data.spec_content:
            context_parts.extend([
                "",
                "**Spec (excerpt):**",
                (input_data.spec_content or "")[:8000] + ("..." if len(input_data.spec_content or "") > 8000 else ""),
            ])
        if input_data.codebase_analysis:
            context_parts.extend(["", "**Codebase Analysis:**", input_data.codebase_analysis[:4000]])
        if input_data.spec_analysis:
            context_parts.extend(["", "**Spec Analysis:**", input_data.spec_analysis[:4000]])

        prompt = BACKEND_PLANNING_PROMPT + "\n\n---\n\n" + "\n".join(context_parts)
        raw = self.llm.complete_text(prompt, temperature=0.2)
        data = parse_planning_template(raw)
        if not data.get("nodes") and raw.strip().startswith("{"):
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                pass
        graph = _parse_graph_from_llm_output(data)
        logger.info("Backend Planning: produced %s nodes, %s edges", len(graph.nodes), len(graph.edges))
        return BackendPlanningOutput(planning_graph=graph, summary=data.get("summary", ""))
