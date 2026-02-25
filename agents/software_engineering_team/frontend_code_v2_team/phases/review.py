"""
Review phase: code review, build verification, lint, QA, security.

Uses passed-in quality agents when available; LLM-based review otherwise.
No code from frontend_team is used.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from shared.llm import LLMClient
from shared.models import Task

from ..models import (
    ExecutionResult,
    Microtask,
    Phase,
    ReviewIssue,
    ReviewResult,
    ToolAgentKind,
    ToolAgentPhaseInput,
)
from ..output_templates import parse_review_template
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
    raw = llm.complete_text(prompt)
    data = parse_review_template(raw)
    issues: List[ReviewIssue] = []
    for item in data.get("issues") or []:
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
    if build_verifier is None:
        return True, "No build verifier provided; skipping."
    try:
        return build_verifier(repo_path, "frontend_code_v2", task_id)
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
    tool_agents: Optional[Dict[ToolAgentKind, Any]] = None,
) -> ReviewResult:
    """Execute the Review phase. Uses passed-in quality agents when available."""
    task_id = task.id
    issues: List[ReviewIssue] = []

    build_ok, build_msg = _run_build_verification(repo_path, build_verifier, task_id)
    if not build_ok:
        issues.append(ReviewIssue(
            source="build",
            severity="critical",
            description=f"Build failed: {build_msg[:300]}",
            recommendation="Fix build errors; consider triggering Build Specialist.",
        ))

    lint_ok = True
    if linting_tool_agent is not None:
        try:
            from linting_tool_agent.models import LintToolInput as _LintInput
            lint_result = linting_tool_agent.run(_LintInput(
                repo_path=str(repo_path),
                agent_type="frontend",
                task_id=task_id,
                task_description=task.description or "",
            ))
            if lint_result and not getattr(
                lint_result.execution_result, "success", getattr(lint_result, "passed", True)
            ):
                lint_ok = False
                for li in getattr(lint_result, "linter_issues", getattr(lint_result, "issues", [])):
                    issues.append(ReviewIssue(
                        source="lint",
                        severity=getattr(li, "severity", "medium"),
                        description=getattr(li, "message", str(li)),
                        file_path=getattr(li, "file_path", ""),
                        recommendation="",
                    ))
        except Exception as exc:
            logger.warning("[%s] Linting tool agent failed: %s", task_id, exc)

    code_text = "\n\n".join(
        f"--- {p} ---\n{c}" for p, c in list(execution_result.files.items())[:20]
    )
    code_text_12k = code_text[:12000]
    if code_review_agent is not None:
        try:
            from code_review_agent.models import CodeReviewInput as _CRInput
            cr_input = _CRInput(
                code=code_text_12k,
                task_description=task.description or "",
                task_requirements=task.requirements or "",
                acceptance_criteria=getattr(task, "acceptance_criteria", []) or [],
                language="typescript",
            )
            cr_result = code_review_agent.run(cr_input)
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

    if qa_agent is not None:
        try:
            from qa_agent.models import QAInput as _QAInput
            qa_input = _QAInput(
                code=code_text_12k,
                language="typescript",
                task_description=task.description or "",
            )
            qa_result = qa_agent.run(qa_input)
            for item in getattr(qa_result, "bugs_found", getattr(qa_result, "issues", [])):
                issues.append(ReviewIssue(
                    source="qa",
                    severity=getattr(item, "severity", "medium"),
                    description=getattr(item, "description", str(item)),
                    file_path=getattr(item, "location", getattr(item, "file_path", "")),
                    recommendation=getattr(item, "recommendation", ""),
                ))
        except Exception as exc:
            logger.warning("[%s] QA agent failed: %s", task_id, exc)

    if security_agent is not None:
        try:
            from security_agent.models import SecurityInput as _SecInput
            sec_input = _SecInput(
                code=code_text_12k,
                language="typescript",
                task_description=task.description or "",
            )
            sec_result = security_agent.run(sec_input)
            for item in getattr(sec_result, "vulnerabilities", getattr(sec_result, "issues", [])):
                issues.append(ReviewIssue(
                    source="security",
                    severity=getattr(item, "severity", "high"),
                    description=getattr(item, "description", str(item)),
                    file_path=getattr(item, "location", getattr(item, "file_path", "")),
                    recommendation=getattr(item, "recommendation", ""),
                ))
        except Exception as exc:
            logger.warning("[%s] Security agent failed: %s", task_id, exc)

    if tool_agents:
        phase_inp = ToolAgentPhaseInput(
            phase=Phase.REVIEW,
            repo_path=str(repo_path),
            current_files=execution_result.files,
            review_issues=issues,
            task_title=task.title or "",
            task_description=task.description or "",
        )
        for kind, agent in tool_agents.items():
            if not hasattr(agent, "review"):
                continue
            try:
                out = agent.review(phase_inp)
                if out.issues:
                    issues.extend(out.issues)
                if out.recommendations:
                    for r in out.recommendations:
                        issues.append(ReviewIssue(source=kind.value, severity="info", description=r, recommendation=""))
            except Exception as exc:
                logger.warning("[%s] Tool agent %s review() failed: %s", task_id, kind.value, exc)

    passed = build_ok and lint_ok and len([i for i in issues if i.severity in ("critical", "high")]) == 0
    summary = f"Review {'passed' if passed else 'failed'}; {len(issues)} issue(s)."
    return ReviewResult(passed=passed, issues=issues, build_ok=build_ok, lint_ok=lint_ok, summary=summary)


def run_microtask_review(
    *,
    llm: LLMClient,
    task: Task,
    microtask: Microtask,
    repo_path: Path,
    files: Dict[str, str],
    build_verifier: Optional[Callable[..., Tuple[bool, str]]] = None,
    qa_agent: Any = None,
    security_agent: Any = None,
    code_review_agent: Any = None,
    linting_tool_agent: Any = None,
    tool_agents: Optional[Dict[ToolAgentKind, Any]] = None,
) -> ReviewResult:
    """
    Run full review on a single microtask's output files.

    This function performs the same checks as run_review() but is scoped to the
    files produced by a single microtask, enabling per-microtask quality gates.
    """
    task_id = task.id
    microtask_id = microtask.id
    issues: List[ReviewIssue] = []

    logger.info("[%s] Running microtask review for %s (%d files)", task_id, microtask_id, len(files))

    build_ok, build_msg = _run_build_verification(repo_path, build_verifier, task_id)
    if not build_ok:
        issues.append(ReviewIssue(
            source="build",
            severity="critical",
            description=f"Build failed after microtask {microtask_id}: {build_msg[:300]}",
            recommendation="Fix build errors before proceeding.",
        ))

    lint_ok = True
    if linting_tool_agent is not None:
        try:
            from linting_tool_agent.models import LintToolInput as _LintInput
            lint_result = linting_tool_agent.run(_LintInput(
                repo_path=str(repo_path),
                agent_type="frontend",
                task_id=task_id,
                task_description=f"Microtask: {microtask.title or microtask_id}",
            ))
            if lint_result and not getattr(
                lint_result.execution_result, "success", getattr(lint_result, "passed", True)
            ):
                lint_ok = False
                for li in getattr(lint_result, "linter_issues", getattr(lint_result, "issues", [])):
                    file_path = getattr(li, "file_path", "")
                    if files and file_path and file_path not in files:
                        continue
                    issues.append(ReviewIssue(
                        source="lint",
                        severity=getattr(li, "severity", "medium"),
                        description=getattr(li, "message", str(li)),
                        file_path=file_path,
                        recommendation="",
                    ))
        except Exception as exc:
            logger.warning("[%s] Linting tool agent failed for microtask %s: %s", task_id, microtask_id, exc)

    code_text = "\n\n".join(f"--- {p} ---\n{c}" for p, c in list(files.items())[:20])
    code_text_12k = code_text[:12000]

    if code_review_agent is not None:
        try:
            from code_review_agent.models import CodeReviewInput as _CRInput
            cr_input = _CRInput(
                code=code_text_12k,
                task_description=f"Microtask: {microtask.description or microtask.title}",
                task_requirements=task.requirements or "",
                acceptance_criteria=getattr(task, "acceptance_criteria", []) or [],
                language="typescript",
            )
            cr_result = code_review_agent.run(cr_input)
            for item in getattr(cr_result, "issues", []):
                issues.append(ReviewIssue(
                    source="code_review",
                    severity=getattr(item, "severity", "medium"),
                    description=getattr(item, "description", str(item)),
                    file_path=getattr(item, "file_path", ""),
                    recommendation=getattr(item, "recommendation", ""),
                ))
        except Exception as exc:
            logger.warning("[%s] Code review agent failed for microtask %s, using LLM fallback: %s", task_id, microtask_id, exc)
            issues.extend(_run_llm_review(llm=llm, task=task, files=files))
    else:
        issues.extend(_run_llm_review(llm=llm, task=task, files=files))

    if qa_agent is not None:
        try:
            from qa_agent.models import QAInput as _QAInput
            qa_input = _QAInput(
                code=code_text_12k,
                language="typescript",
                task_description=f"Microtask: {microtask.description or microtask.title}",
            )
            qa_result = qa_agent.run(qa_input)
            for item in getattr(qa_result, "bugs_found", getattr(qa_result, "issues", [])):
                issues.append(ReviewIssue(
                    source="qa",
                    severity=getattr(item, "severity", "medium"),
                    description=getattr(item, "description", str(item)),
                    file_path=getattr(item, "location", getattr(item, "file_path", "")),
                    recommendation=getattr(item, "recommendation", ""),
                ))
        except Exception as exc:
            logger.warning("[%s] QA agent failed for microtask %s: %s", task_id, microtask_id, exc)

    if security_agent is not None:
        try:
            from security_agent.models import SecurityInput as _SecInput
            sec_input = _SecInput(
                code=code_text_12k,
                language="typescript",
                task_description=f"Microtask: {microtask.description or microtask.title}",
            )
            sec_result = security_agent.run(sec_input)
            for item in getattr(sec_result, "vulnerabilities", getattr(sec_result, "issues", [])):
                issues.append(ReviewIssue(
                    source="security",
                    severity=getattr(item, "severity", "high"),
                    description=getattr(item, "description", str(item)),
                    file_path=getattr(item, "location", getattr(item, "file_path", "")),
                    recommendation=getattr(item, "recommendation", ""),
                ))
        except Exception as exc:
            logger.warning("[%s] Security agent failed for microtask %s: %s", task_id, microtask_id, exc)

    if tool_agents:
        phase_inp = ToolAgentPhaseInput(
            phase=Phase.REVIEW,
            microtask=microtask,
            repo_path=str(repo_path),
            current_files=files,
            review_issues=issues,
            task_title=task.title or "",
            task_description=f"Microtask: {microtask.description or microtask.title}",
            task_id=task_id,
        )
        for kind, agent in tool_agents.items():
            if not hasattr(agent, "review"):
                continue
            try:
                out = agent.review(phase_inp)
                if out.issues:
                    issues.extend(out.issues)
                if out.recommendations:
                    for r in out.recommendations:
                        issues.append(ReviewIssue(source=kind.value, severity="info", description=r, recommendation=""))
            except Exception as exc:
                logger.warning("[%s] Tool agent %s review() failed for microtask %s: %s", task_id, kind.value, microtask_id, exc)

    passed = build_ok and lint_ok and len([i for i in issues if i.severity in ("critical", "high")]) == 0
    summary = f"Microtask {microtask_id} review {'passed' if passed else 'failed'}; {len(issues)} issue(s)."
    logger.info("[%s] %s", task_id, summary)
    return ReviewResult(passed=passed, issues=issues, build_ok=build_ok, lint_ok=lint_ok, summary=summary)
