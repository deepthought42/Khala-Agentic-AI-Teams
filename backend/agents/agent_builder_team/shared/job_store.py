"""
In-memory job store for Agent Builder Team jobs.

Jobs are kept in a thread-safe dict keyed by job_id.
A background thread runs the orchestrator phases after each state transition.
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional

from ..models import BuildJob, BuilderPhase

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_JOBS: Dict[str, BuildJob] = {}


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def save_job(job: BuildJob) -> None:
    with _LOCK:
        _JOBS[job.job_id] = job


def get_job(job_id: str) -> Optional[BuildJob]:
    with _LOCK:
        return _JOBS.get(job_id)


def list_jobs() -> List[BuildJob]:
    with _LOCK:
        return list(_JOBS.values())


def mark_all_running_jobs_failed(reason: str) -> None:
    """Called on server shutdown to mark in-progress jobs as failed."""
    running_phases = {BuilderPhase.DEFINING, BuilderPhase.PLANNING, BuilderPhase.BUILDING, BuilderPhase.REFINING}
    with _LOCK:
        for job in _JOBS.values():
            if job.phase in running_phases:
                job.phase = BuilderPhase.FAILED
                job.error = f"Server shutdown: {reason}"
                job.touch()
    logger.info("Marked all running agent-builder jobs as failed: %s", reason)


# ---------------------------------------------------------------------------
# Background phase execution
# ---------------------------------------------------------------------------


def _run_in_thread(target, *args) -> None:
    t = threading.Thread(target=target, args=args, daemon=True)
    t.start()


def start_define_phase(job: BuildJob) -> None:
    """Kick off the DEFINING phase in a background thread."""
    from ..orchestrator import AgentBuilderOrchestrator

    orchestrator = AgentBuilderOrchestrator()
    _run_in_thread(orchestrator.run_define_phase, job, save_job)


def start_planning_phase(job: BuildJob) -> None:
    """Kick off the PLANNING phase in a background thread."""
    from ..orchestrator import AgentBuilderOrchestrator

    orchestrator = AgentBuilderOrchestrator()
    _run_in_thread(orchestrator.run_planning_phase, job, save_job)


def start_build_phase(job: BuildJob) -> None:
    """Kick off the BUILD phase in a background thread."""
    from ..orchestrator import AgentBuilderOrchestrator

    orchestrator = AgentBuilderOrchestrator()
    _run_in_thread(orchestrator.run_build_phase, job, save_job)
