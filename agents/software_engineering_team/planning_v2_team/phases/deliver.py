"""
Deliver phase: commit and finalize planning artifacts.

Tool agents: System Design, Architecture, User Story.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from shared.llm import LLMClient
from shared.models import PlanningHierarchy

from ..models import (
    DeliverPhaseResult,
    ImplementationPhaseResult,
    ToolAgentKind,
    ToolAgentPhaseInput,
)

logger = logging.getLogger(__name__)


def run_deliver(
    llm: LLMClient,
    spec_content: str,
    repo_path: Path,
    implementation_result: Optional[ImplementationPhaseResult] = None,
    tool_agents: Optional[Dict[ToolAgentKind, Any]] = None,
    hierarchy: Optional[PlanningHierarchy] = None,
) -> DeliverPhaseResult:
    """
    Run Deliver phase with participating tool agents.
    
    Tool agents: System Design, Architecture, User Story.
    Finalizes planning artifacts and optionally commits to git.
    """
    committed = False
    summaries: list[str] = []
    
    tool_agent_input = ToolAgentPhaseInput(
        spec_content=spec_content,
        repo_path=str(repo_path),
        implementation_result=implementation_result,
        hierarchy=hierarchy,
    )
    
    participating_agents = [
        ToolAgentKind.SYSTEM_DESIGN,
        ToolAgentKind.ARCHITECTURE,
        ToolAgentKind.USER_STORY,
    ]
    
    if tool_agents:
        for agent_kind in participating_agents:
            agent = tool_agents.get(agent_kind)
            if agent and hasattr(agent, "deliver"):
                try:
                    result = agent.deliver(tool_agent_input)
                    if result.summary:
                        summaries.append(f"{agent_kind.value}: {result.summary}")
                    logger.info("Deliver: %s completed", agent_kind.value)
                except Exception as e:
                    logger.warning("Deliver: %s failed: %s", agent_kind.value, e)
    
    try:
        if (repo_path / ".git").exists():
            subprocess.run(
                ["git", "add", "plan/"],
                cwd=repo_path,
                check=False,
                capture_output=True,
            )
            
            if (repo_path / "plan").exists():
                subprocess.run(
                    ["git", "add", "plan/*"],
                    cwd=repo_path,
                    check=False,
                    capture_output=True,
                )
            
            r = subprocess.run(
                ["git", "commit", "-m", "chore: planning artifacts"],
                cwd=repo_path,
                capture_output=True,
                text=True,
            )
            committed = r.returncode == 0
            if committed:
                logger.info("Deliver: committed planning artifacts")
            elif "nothing to commit" in (r.stdout + r.stderr):
                logger.info("Deliver: no changes to commit")
                committed = True
    except Exception as e:
        logger.warning("Deliver git commit failed (non-fatal): %s", e)
    
    hierarchy_summary = ""
    if hierarchy:
        init_count = len(hierarchy.initiatives)
        epic_count = sum(len(i.epics) for i in hierarchy.initiatives)
        story_count = sum(len(e.stories) for i in hierarchy.initiatives for e in i.epics)
        task_count = sum(len(s.tasks) for i in hierarchy.initiatives for e in i.epics for s in e.stories)
        hierarchy_summary = f" Hierarchy: {init_count} initiatives, {epic_count} epics, {story_count} stories, {task_count} tasks."
    
    summary = "Planning-v2 artifacts delivered."
    if implementation_result and implementation_result.assets_created:
        summary = f"Deliver complete. Assets: {', '.join(implementation_result.assets_created[:5])}."
        if len(implementation_result.assets_created) > 5:
            summary += f" (+{len(implementation_result.assets_created) - 5} more)"
    
    summary += hierarchy_summary
    
    if committed:
        summary += " Changes committed."
    
    return DeliverPhaseResult(committed=committed, summary=summary)
