"""
Problem-solving phase: root-cause analysis and fix loop.

Processes one issue at a time to keep LLM prompts and responses small.
Each issue gets up to MAX_ITERATIONS_PER_ISSUE attempts; unresolved issues
are returned for the backend v2 agent to turn into fix microtasks.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from shared.llm import LLMClient
from shared.models import Task

from ..models import (
    Phase,
    ProblemSolvingResult,
    ReviewIssue,
    ReviewResult,
    ToolAgentKind,
    ToolAgentPhaseInput,
)
from ..output_templates import (
    parse_problem_solving_template,
    parse_problem_solving_single_issue_template,
)
from ..prompts import (
    PROBLEM_SOLVING_PROMPT,
    PROBLEM_SOLVING_SINGLE_ISSUE_PROMPT,
    PYTHON_CONVENTIONS,
    JAVA_CONVENTIONS,
)

logger = logging.getLogger(__name__)

MAX_ITERATIONS_PER_ISSUE = 10
MAX_RELEVANT_CODE_CHARS = 8000


def _relevant_code_for_issue(
    issue: ReviewIssue,
    current_files: Dict[str, str],
) -> str:
    """Return code context for a single issue: prefer issue's file, else first files."""
    if issue.file_path and issue.file_path in current_files:
        content = current_files[issue.file_path]
        if len(content) <= MAX_RELEVANT_CODE_CHARS:
            return f"--- {issue.file_path} ---\n{content}"
        return f"--- {issue.file_path} ---\n{content[:MAX_RELEVANT_CODE_CHARS]}\n... [truncated]"
    # Fallback: include first few files to stay under limit
    parts: List[str] = []
    total = 0
    for path, content in list(current_files.items())[:10]:
        chunk = f"--- {path} ---\n{content}\n"
        if total + len(chunk) > MAX_RELEVANT_CODE_CHARS:
            remaining = MAX_RELEVANT_CODE_CHARS - total
            if remaining > 200:
                chunk = f"--- {path} ---\n{content[:remaining]}\n... [truncated]"
            else:
                break
        parts.append(chunk)
        total += len(chunk)
    return "\n".join(parts) if parts else "(no code)"


def run_problem_solving(
    *,
    llm: LLMClient,
    task: Task,
    review_result: ReviewResult,
    current_files: Dict[str, str],
    language: str = "python",
    repo_path: str = "",
    tool_agents: Optional[Dict[ToolAgentKind, Any]] = None,
) -> ProblemSolvingResult:
    """
    Analyse review issues and produce fixes, one issue at a time.

    For each actionable issue: identify root cause, implement fix (up to
    MAX_ITERATIONS_PER_ISSUE attempts). Unresolved issues are returned for
    the backend v2 agent to turn into fix microtasks.
    """
    task_id = task.id
    actionable = [i for i in review_result.issues if i.severity in ("critical", "high", "medium")]
    if not actionable:
        logger.info("[%s] Problem-solving: no actionable issues.", task_id)
        return ProblemSolvingResult(resolved=True, files=current_files, summary="No actionable issues.")

    lang_conv = JAVA_CONVENTIONS if language == "java" else PYTHON_CONVENTIONS
    merged = dict(current_files)
    fixes_applied: List[Dict[str, Any]] = []
    summary_parts: List[str] = []
    unresolved_issues: List[ReviewIssue] = []

    for issue_idx, issue in enumerate(actionable):
        desc_short = (issue.description or "")[:80]
        logger.info("[%s] Problem-solving: issue %d/%d — %s", task_id, issue_idx + 1, len(actionable), desc_short)
        working = dict(merged)
        resolved_this = False
        for attempt in range(1, MAX_ITERATIONS_PER_ISSUE + 1):
            relevant_code = _relevant_code_for_issue(issue, working)
            prompt = PROBLEM_SOLVING_SINGLE_ISSUE_PROMPT.format(
                language_conventions=lang_conv,
                source=issue.source or "review",
                severity=issue.severity or "medium",
                description=issue.description or "",
                file_path=issue.file_path or "N/A",
                recommendation=issue.recommendation or "Fix the issue.",
                current_code=relevant_code,
            )
            try:
                raw = llm.complete_text(prompt)
            except Exception as exc:
                logger.warning("[%s] Problem-solving LLM call failed (issue %d, attempt %d): %s", task_id, issue_idx + 1, attempt, exc)
                break
            parsed = parse_problem_solving_single_issue_template(raw)
            fixed_files = parsed.get("files") or {}
            if not fixed_files:
                if parsed.get("resolved"):
                    resolved_this = True
                break
            working.update(fixed_files)
            merged.update(fixed_files)
            fixes_applied.append({
                "issue": desc_short,
                "fix": parsed.get("summary", "updated file(s)"),
                "root_cause": parsed.get("root_cause", ""),
            })
            if parsed.get("resolved"):
                resolved_this = True
                break
        if not resolved_this:
            unresolved_issues.append(issue)
            logger.warning("[%s] Issue unresolved after %d attempts: %s", task_id, MAX_ITERATIONS_PER_ISSUE, desc_short)

    if tool_agents:
        phase_inp = ToolAgentPhaseInput(
            phase=Phase.PROBLEM_SOLVING,
            repo_path=repo_path,
            spec_context=task.description or "",
            language=language,
            current_files=merged,
            review_issues=review_result.issues,
            task_title=task.title or "",
            task_description=task.description or "",
        )
        for kind, agent in tool_agents.items():
            if not hasattr(agent, "problem_solve"):
                continue
            try:
                out = agent.problem_solve(phase_inp)
                if out.files:
                    merged.update(out.files)
                if out.recommendations:
                    fixes_applied.extend([{"source": kind.value, "recommendation": r} for r in out.recommendations])
                    summary_parts.append(f"Tool {kind.value}: {out.summary or 'suggestions applied.'}")
            except Exception as exc:
                logger.warning("[%s] Tool agent %s problem_solve() failed: %s", task_id, kind.value, exc)

    resolved = len(unresolved_issues) == 0
    summary = " ".join(summary_parts) if summary_parts else f"Applied {len(fixes_applied)} fix(s); {len(unresolved_issues)} unresolved."
    logger.info(
        "[%s] Problem-solving: %s — %s (%d unresolved)",
        task_id,
        "resolved" if resolved else "partial",
        summary[:120],
        len(unresolved_issues),
    )
    return ProblemSolvingResult(
        fixes_applied=fixes_applied,
        files=merged,
        summary=summary,
        resolved=resolved,
        unresolved_issues=unresolved_issues,
    )
