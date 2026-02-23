"""
Execution phase: run each microtask via tool agents or general code gen.

No code from ``backend_agent`` is used.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from shared.llm import LLMClient
from shared.models import SystemArchitecture, Task

from ..models import (
    ExecutionResult,
    Microtask,
    MicrotaskStatus,
    PlanningResult,
    ToolAgentKind,
    ToolAgentInput,
    ToolAgentOutput,
)
from ..prompts import EXECUTION_PROMPT, PYTHON_CONVENTIONS, JAVA_CONVENTIONS

logger = logging.getLogger(__name__)

ToolAgentRunner = Callable[[ToolAgentInput], ToolAgentOutput]


def _language_conventions(language: str) -> str:
    return JAVA_CONVENTIONS if language == "java" else PYTHON_CONVENTIONS


def _run_general_microtask(
    *,
    llm: LLMClient,
    microtask: Microtask,
    task: Task,
    language: str,
    existing_code: str,
    architecture: Optional[SystemArchitecture],
) -> Dict[str, str]:
    """Use the LLM to implement a general (non-specialist) microtask."""
    arch_ctx = ""
    if architecture:
        arch_ctx = architecture.overview[:2000]

    prompt = EXECUTION_PROMPT.format(
        language_conventions=_language_conventions(language),
        microtask_description=microtask.description or microtask.title,
        requirements=task.requirements or task.description,
        existing_code=existing_code[:8000] if existing_code else "(none)",
        architecture_context=arch_ctx or "(none)",
    )
    raw = llm.complete_json(prompt)
    return raw.get("files") or {}


def run_execution(
    *,
    llm: LLMClient,
    task: Task,
    planning_result: PlanningResult,
    repo_path: Path,
    spec_content: str = "",
    architecture: Optional[SystemArchitecture] = None,
    existing_code: str = "",
    tool_runners: Optional[Dict[ToolAgentKind, ToolAgentRunner]] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> ExecutionResult:
    """
    Execute all microtasks in dependency order.

    ``tool_runners`` maps ToolAgentKind → callable(ToolAgentInput) → ToolAgentOutput.
    For microtasks whose tool_agent has no runner, fall back to general LLM code gen.
    ``progress_callback(completed, total, current_microtask_title)`` is called after each.
    """
    runners = tool_runners or {}
    all_files: Dict[str, str] = {}
    microtasks = list(planning_result.microtasks)
    completed_ids: set[str] = set()
    total = len(microtasks)

    for idx, mt in enumerate(microtasks):
        deps_met = all(d in completed_ids for d in mt.depends_on)
        if not deps_met:
            logger.warning("[%s] Microtask %s has unmet deps %s — running anyway", task.id, mt.id, mt.depends_on)

        mt.status = MicrotaskStatus.IN_PROGRESS
        logger.info("[%s] Execution: microtask %d/%d — %s (%s)", task.id, idx + 1, total, mt.id, mt.tool_agent.value)

        try:
            runner = runners.get(mt.tool_agent)
            if runner is not None:
                inp = ToolAgentInput(
                    microtask=mt,
                    repo_path=str(repo_path),
                    existing_code=existing_code[:6000] if existing_code else "",
                    spec_context=spec_content[:4000] if spec_content else "",
                    language=planning_result.language,
                )
                out = runner(inp)
                mt.output_files = out.files
                mt.notes = out.summary
            else:
                files = _run_general_microtask(
                    llm=llm,
                    microtask=mt,
                    task=task,
                    language=planning_result.language,
                    existing_code=existing_code,
                    architecture=architecture,
                )
                mt.output_files = files

            all_files.update(mt.output_files)
            mt.status = MicrotaskStatus.COMPLETED
            completed_ids.add(mt.id)
        except Exception as exc:
            logger.error("[%s] Microtask %s failed: %s", task.id, mt.id, exc)
            mt.status = MicrotaskStatus.FAILED
            mt.notes = str(exc)

        if progress_callback:
            progress_callback(len(completed_ids), total, mt.title or mt.id)

    summary = f"Executed {len(completed_ids)}/{total} microtasks; {len(all_files)} files produced."
    return ExecutionResult(files=all_files, microtasks=microtasks, summary=summary)
