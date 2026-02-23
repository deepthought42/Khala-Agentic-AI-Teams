"""
Planning phase: decompose a task into microtasks and assign tool agents.

No code from ``frontend_agent`` is used.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.llm import LLMClient
from shared.models import SystemArchitecture, Task

from ..models import (
    Microtask,
    MicrotaskStatus,
    PlanningResult,
    ToolAgentKind,
)
from ..prompts import PLANNING_PROMPT

logger = logging.getLogger(__name__)


def _detect_language(repo_path: Path, task: Task) -> str:
    """Infer whether the project is Python or Java from the repo."""
    if repo_path.is_dir():
        if any(repo_path.rglob("pom.xml")) or any(repo_path.rglob("build.gradle")):
            return "java"
        if any(repo_path.rglob("requirements.txt")) or any(repo_path.rglob("pyproject.toml")):
            return "python"
        if any(repo_path.rglob("*.java")):
            return "java"
    desc = (task.description or "").lower() + " " + (task.requirements or "").lower()
    if "spring" in desc or "java" in desc or "maven" in desc or "gradle" in desc:
        return "java"
    return "python"


def _build_context(
    task: Task,
    spec_content: str,
    architecture: Optional[SystemArchitecture],
    existing_code: str,
    language: str,
) -> str:
    """Build the full prompt context for the planning LLM call."""
    parts: List[str] = [
        PLANNING_PROMPT,
        "",
        "---",
        "",
        f"**Task title:** {task.title or task.id}",
        f"**Task description:** {task.description}",
        f"**Requirements:** {task.requirements or 'N/A'}",
        f"**Acceptance criteria:** {', '.join(task.acceptance_criteria) if task.acceptance_criteria else 'N/A'}",
        f"**Language:** {language}",
    ]
    if spec_content:
        parts.extend(["", "**Project specification (excerpt):**", spec_content[:6000]])
    if architecture:
        parts.extend(["", "**Architecture overview:**", architecture.overview[:3000]])
    if existing_code and existing_code != "# No code files found":
        parts.extend(["", "**Existing codebase (excerpt):**", existing_code[:6000]])
    return "\n".join(parts)


def _parse_planning_output(raw: Dict[str, Any], language: str) -> PlanningResult:
    """Convert the LLM JSON response into a PlanningResult."""
    microtasks: List[Microtask] = []
    for mt in raw.get("microtasks") or []:
        if not isinstance(mt, dict) or not mt.get("id"):
            continue
        try:
            kind = ToolAgentKind(mt.get("tool_agent", "general"))
        except ValueError:
            kind = ToolAgentKind.GENERAL
        microtasks.append(
            Microtask(
                id=mt["id"],
                title=mt.get("title", ""),
                description=mt.get("description", ""),
                tool_agent=kind,
                status=MicrotaskStatus.PENDING,
                depends_on=mt.get("depends_on") or [],
            )
        )
    return PlanningResult(
        microtasks=microtasks,
        language=raw.get("language") or language,
        summary=raw.get("summary", ""),
    )


def run_planning(
    *,
    llm: LLMClient,
    task: Task,
    repo_path: Path,
    spec_content: str = "",
    architecture: Optional[SystemArchitecture] = None,
    existing_code: str = "",
) -> PlanningResult:
    """Execute the Planning phase and return a PlanningResult."""
    language = _detect_language(repo_path, task)
    prompt = _build_context(task, spec_content, architecture, existing_code, language)

    logger.info("[%s] Planning phase: generating microtasks (language=%s)", task.id, language)
    raw = llm.complete_json(prompt)
    result = _parse_planning_output(raw, language)
    logger.info(
        "[%s] Planning phase: produced %d microtasks — %s",
        task.id, len(result.microtasks), result.summary[:120],
    )

    if not result.microtasks:
        result.microtasks = [
            Microtask(
                id="mt-implement-task",
                title=task.title or "Implement task",
                description=task.description or "Implement the full task as described.",
                tool_agent=ToolAgentKind.GENERAL,
            )
        ]
        result.summary = result.summary or "Single-microtask fallback."
    return result
