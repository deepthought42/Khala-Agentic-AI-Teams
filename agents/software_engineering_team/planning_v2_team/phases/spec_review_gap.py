"""
Spec Review and Gap analysis phase: System Design + Architecture tool agents.

Identifies critical gaps, open questions, and requirements from the spec.
Tool agents: System Design, Architecture.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from shared.llm import LLMClient

from ..models import SpecReviewResult, ToolAgentKind, ToolAgentPhaseInput
from ..prompts import SPEC_REVIEW_PROMPT

logger = logging.getLogger(__name__)


def _parse_spec_review_response(raw: Any) -> SpecReviewResult:
    """Parse LLM JSON response into SpecReviewResult."""
    if not isinstance(raw, dict):
        return SpecReviewResult(summary="Spec review completed (no structured output).")
    gaps = raw.get("gaps")
    open_questions = raw.get("open_questions")
    return SpecReviewResult(
        gaps=list(gaps) if isinstance(gaps, list) else [],
        open_questions=list(open_questions) if isinstance(open_questions, list) else [],
        system_design_notes=str(raw.get("system_design_notes", "") or ""),
        architecture_notes=str(raw.get("architecture_notes", "") or ""),
        summary=str(raw.get("summary", "") or "Spec review complete."),
    )


def run_spec_review_gap(
    llm: LLMClient,
    spec_content: str,
    repo_path: Path,
    inspiration_content: Optional[str] = None,
    tool_agents: Optional[Dict[ToolAgentKind, Any]] = None,
) -> SpecReviewResult:
    """
    Run Spec Review and Gap analysis phase.
    
    Tool agents participating: System Design, Architecture.
    """
    all_gaps: list[str] = []
    all_questions: list[str] = []
    system_design_notes = ""
    architecture_notes = ""
    
    tool_agent_input = ToolAgentPhaseInput(
        spec_content=spec_content,
        inspiration_content=inspiration_content or "",
        repo_path=str(repo_path),
    )
    
    if tool_agents:
        system_design_agent = tool_agents.get(ToolAgentKind.SYSTEM_DESIGN)
        if system_design_agent and hasattr(system_design_agent, "spec_review"):
            try:
                sd_result = system_design_agent.spec_review(tool_agent_input)
                all_gaps.extend(sd_result.issues)
                system_design_notes = sd_result.summary
                logger.info("Spec review: SystemDesign found %d issues", len(sd_result.issues))
            except Exception as e:
                logger.warning("SystemDesign spec_review failed: %s", e)
        
        architecture_agent = tool_agents.get(ToolAgentKind.ARCHITECTURE)
        if architecture_agent and hasattr(architecture_agent, "spec_review"):
            try:
                arch_result = architecture_agent.spec_review(tool_agent_input)
                all_gaps.extend(arch_result.issues)
                architecture_notes = arch_result.summary
                logger.info("Spec review: Architecture found %d issues", len(arch_result.issues))
            except Exception as e:
                logger.warning("Architecture spec_review failed: %s", e)
    
    prompt = SPEC_REVIEW_PROMPT.format(
        spec_content=(spec_content or "")[:12000],
    )
    try:
        raw = llm.complete_json(prompt)
        result = _parse_spec_review_response(raw)
        
        combined_gaps = list(set(all_gaps + result.gaps))
        combined_questions = list(set(all_questions + result.open_questions))
        combined_system_design = system_design_notes or result.system_design_notes
        combined_architecture = architecture_notes or result.architecture_notes
        
        logger.info("Spec review: %d total gaps, %d open questions", len(combined_gaps), len(combined_questions))
        
        return SpecReviewResult(
            gaps=combined_gaps,
            open_questions=combined_questions,
            system_design_notes=combined_system_design,
            architecture_notes=combined_architecture,
            summary=result.summary,
        )
    except Exception as e:
        logger.warning("Spec review LLM call failed, using tool agent results: %s", e)
        return SpecReviewResult(
            gaps=all_gaps,
            open_questions=all_questions,
            system_design_notes=system_design_notes,
            architecture_notes=architecture_notes,
            summary="Spec review completed with tool agents.",
        )
