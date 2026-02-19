"""
Parse LLM JSON output into TaskAssignment.

Shared by Tech Lead and Task Generator agents.
"""

from __future__ import annotations

from typing import Any, Dict, List

from shared.models import Task, TaskAssignment, TaskStatus, TaskType


def parse_assignment_from_data(data: Dict[str, Any]) -> TaskAssignment:
    """
    Parse LLM JSON output into TaskAssignment.
    Filters out security/qa (orchestrator invokes those).
    """
    tasks: List[Task] = []
    for t in data.get("tasks") or []:
        if isinstance(t, dict) and t.get("id"):
            assignee = t.get("assignee") or "devops"
            try:
                task_type = TaskType(t.get("type", "backend"))
            except ValueError:
                task_type = TaskType.BACKEND
            if task_type in (TaskType.SECURITY, TaskType.QA):
                continue
            acc = t.get("acceptance_criteria") or []
            if not isinstance(acc, list):
                acc = [str(acc)] if acc else []
            tasks.append(
                Task(
                    id=t["id"],
                    type=task_type,
                    title=t.get("title") or t.get("name") or t.get("label", ""),
                    description=t.get("description", ""),
                    user_story=t.get("user_story", ""),
                    assignee=assignee,
                    requirements=t.get("requirements", ""),
                    dependencies=t.get("dependencies", []),
                    acceptance_criteria=acc,
                    status=TaskStatus.PENDING,
                )
            )

    execution_order = data.get("execution_order") or [t.id for t in tasks]
    valid_ids = {t.id for t in tasks}
    execution_order = [tid for tid in execution_order if tid in valid_ids]
    execution_order = _interleave_execution_order(execution_order, {t.id: t for t in tasks})

    return TaskAssignment(
        tasks=tasks,
        execution_order=execution_order,
        rationale=data.get("rationale", ""),
    )


def _interleave_execution_order(
    execution_order: List[str],
    tasks_by_id: Dict[str, Any],
) -> List[str]:
    """Enforce interleaving of backend and frontend tasks."""
    prefix: List[str] = []
    backend_queue: List[str] = []
    frontend_queue: List[str] = []

    for tid in execution_order:
        task = tasks_by_id.get(tid)
        if not task:
            prefix.append(tid)
            continue
        assignee = getattr(task, "assignee", None) or ""
        if assignee == "backend":
            backend_queue.append(tid)
        elif assignee == "frontend":
            frontend_queue.append(tid)
        else:
            prefix.append(tid)

    interleaved: List[str] = []
    bi, fi = 0, 0
    while bi < len(backend_queue) or fi < len(frontend_queue):
        if bi < len(backend_queue):
            interleaved.append(backend_queue[bi])
            bi += 1
        if fi < len(frontend_queue):
            interleaved.append(frontend_queue[fi])
            fi += 1

    return prefix + interleaved
