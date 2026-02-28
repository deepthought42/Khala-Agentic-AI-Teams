"""
Problem-solving phase: identify root causes and fix inconsistencies.

Tool agents: System Design, Architecture, User Story.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from shared.llm import LLMClient

from ..models import (
    ImplementationPhaseResult,
    PlanningPhaseResult,
    ProblemSolvingPhaseResult,
    ReviewPhaseResult,
    SpecReviewResult,
    ToolAgentKind,
    ToolAgentPhaseInput,
)
from ..prompts import PROBLEM_SOLVING_PROMPT

logger = logging.getLogger(__name__)


def run_problem_solving(
    llm: LLMClient,
    spec_content: str,
    repo_path: Path,
    spec_review_result: Optional[SpecReviewResult] = None,
    planning_result: Optional[PlanningPhaseResult] = None,
    implementation_result: Optional[ImplementationPhaseResult] = None,
    review_result: Optional[ReviewPhaseResult] = None,
    tool_agents: Optional[Dict[ToolAgentKind, Any]] = None,
) -> ProblemSolvingPhaseResult:
    """
    Run Problem-solving phase with participating tool agents.
    
    Tool agents: System Design, Architecture, User Story.
    """
    all_fixes: list[str] = []
    review_issues = review_result.issues if review_result else []
    
    if not review_issues:
        return ProblemSolvingPhaseResult(
            fixes_applied=[],
            resolved=True,
            summary="No issues to fix.",
        )
    
    tool_agent_input = ToolAgentPhaseInput(
        spec_content=spec_content,
        repo_path=str(repo_path),
        spec_review_result=spec_review_result,
        planning_result=planning_result,
        implementation_result=implementation_result,
        review_result=review_result,
        review_issues=review_issues,
    )
    
    participating_agents = [
        ToolAgentKind.SYSTEM_DESIGN,
        ToolAgentKind.ARCHITECTURE,
        ToolAgentKind.USER_STORY,
    ]
    
    if tool_agents:
        for agent_kind in participating_agents:
            agent = tool_agents.get(agent_kind)
            if agent and hasattr(agent, "problem_solve"):
                try:
                    result = agent.problem_solve(tool_agent_input)
                    all_fixes.extend(result.recommendations)
                    logger.info("Problem-solving: %s provided %d fixes", agent_kind.value, len(result.recommendations))
                except Exception as e:
                    logger.warning("Problem-solving: %s failed: %s", agent_kind.value, e)
    
    issues_str = "; ".join(review_issues[:10])
    prompt = PROBLEM_SOLVING_PROMPT.format(issues=issues_str[:2000])
    try:
        raw = llm.complete_json(prompt)
        if not isinstance(raw, dict):
            return ProblemSolvingPhaseResult(
                fixes_applied=all_fixes,
                resolved=len(all_fixes) > 0,
                summary="Problem-solving complete (tool agents only).",
            )
        
        llm_fixes = raw.get("fixes_applied") or []
        if isinstance(llm_fixes, list):
            all_fixes.extend(llm_fixes)
        
        resolved = bool(raw.get("resolved", len(all_fixes) > 0))
        
        return ProblemSolvingPhaseResult(
            fixes_applied=list(set(all_fixes)),
            resolved=resolved,
            summary=str(raw.get("summary", "") or f"Problem-solving complete. {len(all_fixes)} fix(es) applied."),
        )
    except Exception as e:
        logger.warning("Problem-solving LLM call failed: %s", e)
        return ProblemSolvingPhaseResult(
            fixes_applied=all_fixes,
            resolved=len(all_fixes) > 0,
            summary="Problem-solving completed with tool agents.",
        )
