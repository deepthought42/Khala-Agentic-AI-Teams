"""
Review phase: code review, build verification, lint, QA, security.

Invokes passed-in quality agents when available; otherwise uses the team's
own LLM-based review. No code from ``backend_agent`` is used.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from shared.llm import LLMClient
from shared.models import Task

from ..models import ExecutionResult, ReviewIssue, ReviewResult
from ..prompts import REVIEW_PROMPT

logger = logging.getLogger(__name__)


def _run_llm_review(
    *,
    llm: LLMClient,
    task: Task,
    files: Dict[str, str],
) -> List[ReviewIssue]:
    """LLM-based code review when no external review agent is available."""
    code_text = "\n\n".join(f"--- {p} ---\n{c}" for p, c in list(files.items())[:20])
    prompt = REVIEW_PROMPT.format(
        requirements=task.requirements or task.description,
        acceptance_criteria=", ".join(task.acceptance_criteria) if task.acceptance_criteria else "N/A",
        code=code_text[:12000],
    )
    raw = llm.complete_json(prompt)
    issues: List[ReviewIssue] = []
    for item in raw.get("issues") or []:
        if isinstance(item, dict):
            issues.append(ReviewIssue(
                source=item.get("source", "code_review"),
                severity=item.get("severity", "medium"),
                description=item.get("description", ""),
                file_path=item.get("file_path", ""),
                recommendation=item.get("recommendation", ""),
            ))
    return issues


def _run_build_verification(
    repo_path: Path,
    build_verifier: Optional[Callable[..., Tuple[bool, str]]],
    task_id: str,
) -> Tuple[bool, str]:
    """Run the build verifier if provided, else assume success."""
    if build_verifier is None:
        return True, "No build verifier provided; skipping."
    try:
        return build_verifier(repo_path, "backend_code_v2", task_id)
    except Exception as exc:
        logger.warning("[%s] Build verifier raised: %s", task_id, exc)
        return False, str(exc)


def run_review(
    *,
    llm: LLMClient,
    task: Task,
    execution_result: ExecutionResult,
    repo_path: Path,
    build_verifier: Optional[Callable[..., Tuple[bool, str]]] = None,
    qa_agent: Any = None,
    security_agent: Any = None,
    code_review_agent: Any = None,
    linting_tool_agent: Any = None,
) -> ReviewResult:
    """
    Execute the Review phase.

    Uses passed-in quality agents (from the main orchestrator) when available,
    falls back to team-internal LLM review otherwise.
    """
    task_id = task.id
    issues: List[ReviewIssue] = []

    # 1. Build verification
    build_ok, build_msg = _run_build_verification(repo_path, build_verifier, task_id)
    if not build_ok:
        issues.append(ReviewIssue(
            source="build",
            severity="critical",
            description=f"Build failed: {build_msg[:300]}",
            recommendation="Fix compilation/test errors before proceeding.",
        ))

    # 2. Lint verification
    lint_ok = True
    if linting_tool_agent is not None:
        try:
            from linting_tool_agent.models import LintToolInput as _LintInput
            lint_result = linting_tool_agent.run(_LintInput(
                repo_path=str(repo_path),
                task_id=task_id,
                language="python",
            ))
            if lint_result and not getattr(lint_result, "passed", True):
                lint_ok = False
                for li in getattr(lint_result, "issues", []):
                    issues.append(ReviewIssue(
                        source="lint",
                        severity="medium",
                        description=getattr(li, "message", str(li)),
                        file_path=getattr(li, "file_path", ""),
                        recommendation=getattr(li, "fix", ""),
                    ))
        except Exception as exc:
            logger.warning("[%s] Linting tool agent failed: %s", task_id, exc)

    # 3. Code review agent (external) or LLM fallback
    if code_review_agent is not None:
        try:
            cr_result = code_review_agent.run(execution_result.files, task)
            for item in getattr(cr_result, "issues", []):
                issues.append(ReviewIssue(
                    source="code_review",
                    severity=getattr(item, "severity", "medium"),
                    description=getattr(item, "description", str(item)),
                    file_path=getattr(item, "file_path", ""),
                    recommendation=getattr(item, "recommendation", ""),
                ))
        except Exception as exc:
            logger.warning("[%s] Code review agent failed, using LLM fallback: %s", task_id, exc)
            issues.extend(_run_llm_review(llm=llm, task=task, files=execution_result.files))
    else:
        issues.extend(_run_llm_review(llm=llm, task=task, files=execution_result.files))

    # 4. QA agent
    if qa_agent is not None:
        try:
            qa_result = qa_agent.run(execution_result.files, task)
            for item in getattr(qa_result, "issues", []):
                issues.append(ReviewIssue(
                    source="qa",
                    severity=getattr(item, "severity", "medium"),
                    description=getattr(item, "description", str(item)),
                    recommendation=getattr(item, "recommendation", ""),
                ))
        except Exception as exc:
            logger.warning("[%s] QA agent failed: %s", task_id, exc)

    # 5. Security agent
    if security_agent is not None:
        try:
            sec_result = security_agent.run(execution_result.files, task)
            for item in getattr(sec_result, "issues", []):
                issues.append(ReviewIssue(
                    source="security",
                    severity=getattr(item, "severity", "high"),
                    description=getattr(item, "description", str(item)),
                    recommendation=getattr(item, "recommendation", ""),
                ))
        except Exception as exc:
            logger.warning("[%s] Security agent failed: %s", task_id, exc)

    critical_or_high = [i for i in issues if i.severity in ("critical", "high")]
    passed = build_ok and len(critical_or_high) == 0

    summary = f"Review: build={'OK' if build_ok else 'FAIL'}, lint={'OK' if lint_ok else 'FAIL'}, {len(issues)} issues ({len(critical_or_high)} critical/high)."
    logger.info("[%s] %s passed=%s", task_id, summary, passed)

    return ReviewResult(
        passed=passed,
        issues=issues,
        build_ok=build_ok,
        lint_ok=lint_ok,
        summary=summary,
    )
