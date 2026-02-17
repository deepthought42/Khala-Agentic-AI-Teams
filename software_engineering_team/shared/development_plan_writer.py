"""
Write development plans produced by planning agents to markdown files.

Files are named DEVELOPMENT_PLAN-[AGENT_TYPE].md and written to the work path (repo root).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from shared.models import Task, TaskAssignment, SystemArchitecture

logger = logging.getLogger(__name__)

DEVELOPMENT_PLAN_PREFIX = "DEVELOPMENT_PLAN-"


def _normalize_mermaid(content: str) -> str:
    """Strip existing mermaid code fences if present, return raw Mermaid."""
    s = content.strip()
    # Match ```mermaid or ``` mermaid at start, ``` at end
    match = re.match(r"^```\s*mermaid\s*\n(.*)\n?```\s*$", s, re.DOTALL)
    if match:
        return match.group(1).strip()
    return s


def write_architecture_plan(repo_path: str | Path, architecture: SystemArchitecture) -> Path:
    """
    Write the architecture plan to DEVELOPMENT_PLAN-architecture.md.
    Returns the path of the written file.
    """
    path = Path(repo_path).resolve()
    path.mkdir(parents=True, exist_ok=True)
    out_file = path / f"{DEVELOPMENT_PLAN_PREFIX}architecture.md"

    sections: List[str] = [
        "# Development Plan: Architecture",
        "",
        "## Overview",
        "",
        architecture.overview.strip() or "(No overview provided.)",
        "",
    ]

    if architecture.architecture_document and architecture.architecture_document.strip():
        sections.extend(["## Architecture Document", "", architecture.architecture_document.strip(), ""])

    if architecture.components:
        sections.extend(["## Components", ""])
        for c in architecture.components:
            sections.append(f"### {c.name}")
            sections.append(f"- **Type:** {c.type}")
            if c.technology:
                sections.append(f"- **Technology:** {c.technology}")
            if c.description:
                sections.append(f"- **Description:** {c.description}")
            if c.dependencies:
                sections.append(f"- **Dependencies:** {', '.join(c.dependencies)}")
            if c.interfaces:
                sections.append(f"- **Interfaces:** {', '.join(c.interfaces)}")
            sections.append("")

    if architecture.diagrams:
        sections.extend(["## Diagrams", ""])
        for name, content in architecture.diagrams.items():
            mermaid = _normalize_mermaid(content)
            sections.extend([f"### {name}", "", "```mermaid", mermaid, "```", ""])

    if architecture.decisions:
        sections.extend(["## Architecture Decisions", ""])
        for d in architecture.decisions:
            if isinstance(d, dict):
                title = d.get("title") or d.get("name") or "Decision"
                sections.append(f"### {title}")
                for k, v in d.items():
                    if k not in ("title", "name") and v is not None:
                        sections.append(f"- **{k}:** {v}")
            else:
                sections.append(f"- {d}")
            sections.append("")

    content = "\n".join(sections)
    out_file.write_text(content, encoding="utf-8")
    logger.info("Wrote development plan to %s", out_file)
    return out_file


def write_tech_lead_plan(
    repo_path: str | Path,
    assignment: TaskAssignment,
    summary: str = "",
    requirement_task_mapping: List[Dict[str, Any]] | None = None,
) -> Path:
    """
    Write the Tech Lead task plan to DEVELOPMENT_PLAN-tech_lead.md.
    Includes all tasks with full details and execution order.
    Returns the path of the written file.
    """
    path = Path(repo_path).resolve()
    path.mkdir(parents=True, exist_ok=True)
    out_file = path / f"{DEVELOPMENT_PLAN_PREFIX}tech_lead.md"

    sections: List[str] = [
        "# Development Plan: Tech Lead",
        "",
        "## Summary",
        "",
        summary.strip() or "(No summary provided.)",
        "",
    ]

    if assignment.rationale:
        sections.extend(["## Rationale", "", assignment.rationale.strip(), ""])

    if requirement_task_mapping:
        sections.extend(["## Requirement → Task Mapping", ""])
        for m in requirement_task_mapping:
            spec_item = m.get("spec_item", "")
            task_ids = m.get("task_ids", [])
            sections.append(f"- **{spec_item}** → {', '.join(task_ids)}")
        sections.append("")

    sections.extend(["## Execution Order", ""])
    sections.append(", ".join(assignment.execution_order))
    sections.append("")
    sections.extend(["## Tasks", ""])

    for task in assignment.tasks:
        t = task if isinstance(task, Task) else task
        sections.extend([
            f"### {t.id}",
            "",
            f"- **Title:** {t.title}",
            f"- **Type:** {t.type.value if hasattr(t.type, 'value') else t.type}",
            f"- **Assignee:** {t.assignee}",
            "",
            "#### Description",
            "",
            t.description.strip() or "(No description.)",
            "",
        ])
        if t.user_story:
            sections.extend(["#### User Story", "", t.user_story.strip(), ""])
        if t.requirements:
            sections.extend(["#### Requirements", "", t.requirements.strip(), ""])
        if t.acceptance_criteria:
            sections.extend(["#### Acceptance Criteria", ""])
            for ac in t.acceptance_criteria:
                sections.append(f"- {ac}")
            sections.append("")
        if t.dependencies:
            sections.append(f"**Dependencies:** {', '.join(t.dependencies)}")
            sections.append("")
        sections.append("---")
        sections.append("")

    content = "\n".join(sections)
    out_file.write_text(content, encoding="utf-8")
    logger.info("Wrote development plan to %s", out_file)
    return out_file
