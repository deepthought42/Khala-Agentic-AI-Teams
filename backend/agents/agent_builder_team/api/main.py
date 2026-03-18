"""
FastAPI endpoints for the Agent Builder Team.

Workflow:
  POST /agent-builder/jobs                          — start build (submit process description)
  GET  /agent-builder/jobs                          — list all jobs
  GET  /agent-builder/jobs/{job_id}                 — get job status / results
  PUT  /agent-builder/jobs/{job_id}/approve-flowchart — approve or revise the generated flowchart
  PUT  /agent-builder/jobs/{job_id}/approve-plan      — approve or revise the agent plan
  GET  /health                                       — health check
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import FastAPI, HTTPException

from agent_builder_team.models import (
    ApprovePlanRequest,
    ApproveFlowchartRequest,
    BuilderPhase,
    BuildJob,
    JobStatusResponse,
    StartBuildRequest,
)
from agent_builder_team.shared.job_store import (
    get_job,
    list_jobs,
    mark_all_running_jobs_failed,
    save_job,
    start_build_phase,
    start_define_phase,
    start_planning_phase,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Agent Builder Team API",
    description=(
        "Meta-team that builds other agent teams. "
        "Guides the user through process definition → flowchart → agent plan → code generation."
    ),
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _job_or_404(job_id: str) -> BuildJob:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")
    return job


def _job_to_response(job: BuildJob) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=job.job_id,
        phase=job.phase,
        process_description=job.process_description,
        flowchart=job.flowchart,
        agent_plan=job.agent_plan,
        generated_files=[{"filename": f.filename, "content": f.content, "description": f.description}
                         for f in job.generated_files],
        delivery_notes=job.delivery_notes,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.post("/agent-builder/jobs", response_model=JobStatusResponse, status_code=202)
def start_build(payload: StartBuildRequest) -> JobStatusResponse:
    """
    Start a new agent team build.

    Submit a natural-language description of the process you want to automate.
    The team will generate a flowchart for your review before building anything.

    Returns immediately with a job_id; poll GET /agent-builder/jobs/{job_id} for progress.
    """
    job = BuildJob(process_description=payload.process_description)
    save_job(job)
    start_define_phase(job)
    logger.info("Started agent-builder job %s", job.job_id)
    return _job_to_response(job)


@app.get("/agent-builder/jobs", response_model=List[JobStatusResponse])
def get_all_jobs() -> List[JobStatusResponse]:
    """List all agent builder jobs (most recent activity first)."""
    jobs = sorted(list_jobs(), key=lambda j: j.updated_at, reverse=True)
    return [_job_to_response(j) for j in jobs]


@app.get("/agent-builder/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str) -> JobStatusResponse:
    """
    Get job status and results.

    Phase guide:
    - **defining**: Flowchart is being generated — poll until phase changes.
    - **awaiting_flowchart_approval**: Review `flowchart` and call approve-flowchart.
    - **planning**: Agent plan is being designed — poll until phase changes.
    - **awaiting_plan_approval**: Review `agent_plan` and call approve-plan.
    - **building / refining**: Code is being generated — poll until delivered.
    - **delivered**: `generated_files` contains the complete team source code.
    - **failed**: `error` field describes what went wrong.
    """
    return _job_to_response(_job_or_404(job_id))


@app.put("/agent-builder/jobs/{job_id}/approve-flowchart", response_model=JobStatusResponse)
def approve_flowchart(job_id: str, payload: ApproveFlowchartRequest) -> JobStatusResponse:
    """
    Approve or request revision of the generated flowchart.

    - `approved=true`: proceed to agent planning.
    - `approved=false`: provide `feedback` to regenerate the flowchart before approving.

    Only valid when the job is in phase `awaiting_flowchart_approval`.
    """
    job = _job_or_404(job_id)

    if job.phase != BuilderPhase.AWAITING_FLOWCHART_APPROVAL:
        raise HTTPException(
            status_code=409,
            detail=f"Job is in phase '{job.phase}'; approve-flowchart requires 'awaiting_flowchart_approval'.",
        )

    job.flowchart_feedback = (payload.feedback or "").strip()

    if payload.approved:
        job.phase = BuilderPhase.PLANNING
        job.touch()
        save_job(job)
        start_planning_phase(job)
    else:
        # Regenerate flowchart with the provided feedback incorporated
        job.phase = BuilderPhase.DEFINING
        job.touch()
        save_job(job)
        start_define_phase(job)

    return _job_to_response(job)


@app.put("/agent-builder/jobs/{job_id}/approve-plan", response_model=JobStatusResponse)
def approve_plan(job_id: str, payload: ApprovePlanRequest) -> JobStatusResponse:
    """
    Approve or request revision of the agent plan.

    - `approved=true`: proceed to code generation.
    - `approved=false`: provide `feedback` to revise the plan before approving.

    Only valid when the job is in phase `awaiting_plan_approval`.
    """
    job = _job_or_404(job_id)

    if job.phase != BuilderPhase.AWAITING_PLAN_APPROVAL:
        raise HTTPException(
            status_code=409,
            detail=f"Job is in phase '{job.phase}'; approve-plan requires 'awaiting_plan_approval'.",
        )

    job.plan_feedback = (payload.feedback or "").strip()

    if payload.approved:
        job.phase = BuilderPhase.BUILDING
        job.touch()
        save_job(job)
        start_build_phase(job)
    else:
        # Replan with the provided feedback
        job.phase = BuilderPhase.PLANNING
        job.touch()
        save_job(job)
        start_planning_phase(job)

    return _job_to_response(job)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
