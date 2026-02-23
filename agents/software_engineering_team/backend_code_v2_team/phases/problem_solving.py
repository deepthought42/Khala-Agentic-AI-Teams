"""
Problem-solving phase: root-cause analysis and fix loop.

No code from ``backend_agent`` is used.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from shared.llm import LLMClient
from shared.models import Task

from ..models import ProblemSolvingResult, ReviewIssue, ReviewResult
from ..prompts import PROBLEM_SOLVING_PROMPT, PYTHON_CONVENTIONS, JAVA_CONVENTIONS

logger = logging.getLogger(__name__)


def run_problem_solving(
    *,
    llm: LLMClient,
    task: Task,
    review_result: ReviewResult,
    current_files: Dict[str, str],
    language: str = "python",
) -> ProblemSolvingResult:
    """
    Analyse review issues and produce fixes.

    Returns updated files and a summary of what was changed.
    """
    task_id = task.id
    actionable = [i for i in review_result.issues if i.severity in ("critical", "high", "medium")]
    if not actionable:
        logger.info("[%s] Problem-solving: no actionable issues.", task_id)
        return ProblemSolvingResult(resolved=True, files=current_files, summary="No actionable issues.")

    issues_text = "\n".join(
        f"- [{i.severity}] {i.description} (file: {i.file_path or 'N/A'}) → {i.recommendation}"
        for i in actionable
    )
    code_text = "\n\n".join(f"--- {p} ---\n{c}" for p, c in list(current_files.items())[:20])

    lang_conv = JAVA_CONVENTIONS if language == "java" else PYTHON_CONVENTIONS
    prompt = PROBLEM_SOLVING_PROMPT.format(
        language_conventions=lang_conv,
        issues=issues_text,
        current_code=code_text[:12000],
    )

    logger.info("[%s] Problem-solving: sending %d issues to LLM for fixes", task_id, len(actionable))
    raw = llm.complete_json(prompt)

    fixed_files = raw.get("files") or {}
    merged = dict(current_files)
    merged.update(fixed_files)

    fixes_applied = raw.get("fixes_applied") or []
    resolved = raw.get("resolved", bool(fixed_files))
    summary = raw.get("summary", f"Applied {len(fixes_applied)} fixes.")

    logger.info("[%s] Problem-solving: %s — %s", task_id, "resolved" if resolved else "partial", summary[:120])

    return ProblemSolvingResult(
        fixes_applied=fixes_applied,
        files=merged,
        summary=summary,
        resolved=resolved,
    )
