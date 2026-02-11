"""
Task cache: stores task plan for a job. Integrated with job_store -
tasks and execution_order are stored in the job file.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .job_store import get_job, update_job

logger = logging.getLogger(__name__)


def save_tasks(
    job_id: str,
    tasks: List[Dict[str, Any]],
    execution_order: List[str],
    cache_dir: str | Path = ".agent_cache",
) -> None:
    """Save task plan to job."""
    update_job(
        job_id,
        cache_dir=cache_dir,
        tasks=tasks,
        execution_order=execution_order,
    )


def get_tasks(job_id: str, cache_dir: str | Path = ".agent_cache") -> tuple[List[Dict[str, Any]], List[str]]:
    """Get tasks and execution_order from job. Returns ([], []) if not found."""
    data = get_job(job_id, cache_dir)
    if not data:
        return [], []
    return (
        data.get("tasks", []),
        data.get("execution_order", []),
    )


def update_task(
    job_id: str,
    task_id: str,
    updates: Dict[str, Any],
    cache_dir: str | Path = ".agent_cache",
) -> None:
    """Update a single task in the job."""
    data = get_job(job_id, cache_dir)
    if not data:
        return
    tasks = data.get("tasks", [])
    for i, t in enumerate(tasks):
        if t.get("id") == task_id:
            tasks[i] = {**t, **updates}
            break
    update_job(job_id, cache_dir=cache_dir, tasks=tasks)
