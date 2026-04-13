"""Background workflow orchestrator for the founder agent.

Runs the full lifecycle: spec generation -> product analysis -> SE team execution,
answering all questions autonomously through the founder persona.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from job_service_client import JobServiceClient
from user_agent_founder.agent import FounderAgent
from user_agent_founder.store import FounderRunStore

logger = logging.getLogger(__name__)

_job_client = JobServiceClient(team="user_agent_founder")

UNIFIED_API_BASE = os.environ.get("UNIFIED_API_BASE_URL", "http://localhost:8080")
SE_PREFIX = "/api/software-engineering"

ANALYSIS_POLL_INTERVAL = int(os.environ.get("FOUNDER_ANALYSIS_POLL_SECONDS", "15"))
EXECUTION_POLL_INTERVAL = int(os.environ.get("FOUNDER_EXECUTION_POLL_SECONDS", "30"))
MAX_POLL_ATTEMPTS = int(os.environ.get("FOUNDER_MAX_POLL_ATTEMPTS", "480"))  # ~4h at 30s

# httpx timeout: generous because SE team operations can be slow
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _se_url(path: str) -> str:
    return f"{UNIFIED_API_BASE}{SE_PREFIX}{path}"


def _sync_job_status(run_id: str, status: str, *, phase: str = "", error: str = "") -> None:
    """Mirror a run status update into the centralized job service."""
    try:
        _job_client.update_job(run_id, status=status, current_phase=phase, error=error or None)
    except Exception:
        logger.debug("Job service sync failed for %s (non-fatal)", run_id, exc_info=True)


def _heartbeat(run_id: str) -> None:
    """Touch the heartbeat so the stale-job monitor doesn't kill a waiting job."""
    try:
        _job_client.heartbeat(run_id)
    except Exception:
        pass


def _answer_pending_questions(
    client: httpx.Client,
    agent: FounderAgent,
    store: FounderRunStore,
    run_id: str,
    job_id: str,
    questions: list[dict[str, Any]],
    endpoint_prefix: str,
) -> None:
    """Use the founder agent to answer all pending questions and submit them."""
    answers = []
    for q in questions:
        if not q.get("id"):
            continue
        result = agent.answer_question(q)
        store.add_decision(
            run_id=run_id,
            question_id=q["id"],
            question_text=q.get("question_text", ""),
            answer_text=result.get("other_text") or result.get("selected_option_id", ""),
            rationale=result.get("rationale", ""),
        )
        answer_payload: dict[str, Any] = {
            "question_id": q["id"],
            "selected_option_id": result["selected_option_id"],
        }
        if result["selected_option_id"] == "other" and result.get("other_text"):
            answer_payload["other_text"] = result["other_text"]
        answers.append(answer_payload)

    if answers:
        resp = client.post(
            _se_url(f"{endpoint_prefix}/{job_id}/answers"),
            json={"answers": answers},
            timeout=HTTP_TIMEOUT,
        )
        if resp.status_code >= 400:
            logger.warning(
                "Failed to submit answers for job %s: %s %s",
                job_id,
                resp.status_code,
                resp.text[:500],
            )


def _run_product_analysis(
    client: httpx.Client,
    agent: FounderAgent,
    store: FounderRunStore,
    run_id: str,
    spec_content: str,
) -> str | None:
    """Submit spec for product analysis and poll until complete. Returns repo_path or None."""
    store.update_run(run_id, status="submitting_analysis")
    _sync_job_status(run_id, "running", phase="submitting_analysis")

    resp = client.post(
        _se_url("/product-analysis/start-from-spec"),
        json={"project_name": "taskflow-mvp", "spec_content": spec_content},
        timeout=HTTP_TIMEOUT,
    )
    if resp.status_code >= 400:
        store.update_run(
            run_id,
            status="failed",
            error=f"Failed to start analysis: {resp.status_code} {resp.text[:500]}",
        )
        _sync_job_status(run_id, "failed", error="Failed to start analysis")
        return None

    data = resp.json()
    analysis_job_id = data.get("job_id")
    store.update_run(run_id, analysis_job_id=analysis_job_id, status="polling_analysis")
    _sync_job_status(run_id, "running", phase="polling_analysis")
    logger.info("Product analysis started: job_id=%s", analysis_job_id)

    for _ in range(MAX_POLL_ATTEMPTS):
        time.sleep(ANALYSIS_POLL_INTERVAL)
        _heartbeat(run_id)

        resp = client.get(
            _se_url(f"/product-analysis/status/{analysis_job_id}"),
            timeout=HTTP_TIMEOUT,
        )
        if resp.status_code >= 400:
            logger.warning("Analysis poll error: %s", resp.status_code)
            continue

        status_data = resp.json()
        status = status_data.get("status", "")

        # Answer pending questions
        if status_data.get("waiting_for_answers") and status_data.get("pending_questions"):
            store.update_run(run_id, status="answering_analysis_questions")
            _answer_pending_questions(
                client,
                agent,
                store,
                run_id,
                analysis_job_id,
                status_data["pending_questions"],
                "/product-analysis",
            )
            continue

        if status == "completed":
            repo_path = status_data.get("repo_path")
            store.update_run(run_id, repo_path=repo_path)
            logger.info("Product analysis completed: repo_path=%s", repo_path)
            return repo_path

        if status == "failed":
            store.update_run(
                run_id,
                status="failed",
                error=f"Product analysis failed: {status_data.get('error', 'unknown')}",
            )
            _sync_job_status(run_id, "failed", error="Product analysis failed")
            return None

    store.update_run(run_id, status="failed", error="Product analysis timed out")
    _sync_job_status(run_id, "failed", error="Product analysis timed out")
    return None


def _run_se_team(
    client: httpx.Client,
    agent: FounderAgent,
    store: FounderRunStore,
    run_id: str,
    repo_path: str,
) -> bool:
    """Start the SE team build and poll until complete. Returns True on success."""
    store.update_run(run_id, status="submitting_build")
    _sync_job_status(run_id, "running", phase="submitting_build")

    resp = client.post(
        _se_url("/run-team"),
        json={"repo_path": repo_path},
        timeout=HTTP_TIMEOUT,
    )
    if resp.status_code >= 400:
        store.update_run(
            run_id,
            status="failed",
            error=f"Failed to start SE team: {resp.status_code} {resp.text[:500]}",
        )
        _sync_job_status(run_id, "failed", error="Failed to start SE team")
        return False

    data = resp.json()
    se_job_id = data.get("job_id")
    store.update_run(run_id, se_job_id=se_job_id, status="polling_build")
    _sync_job_status(run_id, "running", phase="polling_build")
    logger.info("SE team build started: job_id=%s", se_job_id)

    for _ in range(MAX_POLL_ATTEMPTS):
        time.sleep(EXECUTION_POLL_INTERVAL)
        _heartbeat(run_id)

        resp = client.get(
            _se_url(f"/run-team/{se_job_id}"),
            timeout=HTTP_TIMEOUT,
        )
        if resp.status_code >= 400:
            logger.warning("Build poll error: %s", resp.status_code)
            continue

        status_data = resp.json()
        status = status_data.get("status", "")

        # Answer pending questions
        if status_data.get("waiting_for_answers") and status_data.get("pending_questions"):
            store.update_run(run_id, status="answering_build_questions")
            _answer_pending_questions(
                client,
                agent,
                store,
                run_id,
                se_job_id,
                status_data["pending_questions"],
                "/run-team",
            )
            continue

        if status == "completed":
            logger.info("SE team build completed for run %s", run_id)
            return True

        if status == "failed":
            store.update_run(
                run_id,
                status="failed",
                error=f"SE team build failed: {status_data.get('error', 'unknown')}",
            )
            _sync_job_status(run_id, "failed", error="SE team build failed")
            return False

        if status == "cancelled":
            store.update_run(run_id, status="failed", error="SE team build was cancelled")
            _sync_job_status(run_id, "failed", error="SE team build cancelled")
            return False

    store.update_run(run_id, status="failed", error="SE team build timed out")
    _sync_job_status(run_id, "failed", error="SE team build timed out")
    return False


def run_workflow(run_id: str, store: FounderRunStore, agent: FounderAgent) -> None:
    """Execute the full founder workflow: spec -> analysis -> build.

    This function is designed to run in a background thread.
    """
    logger.info("Starting founder workflow: run_id=%s", run_id)

    # Register with centralized job service so the Jobs Dashboard can track us.
    try:
        _job_client.create_job(run_id, status="running", label="Persona: founder workflow", current_phase="starting")
    except Exception:
        logger.debug("Job service create failed for %s (non-fatal)", run_id, exc_info=True)

    try:
        # Phase 1: Generate the product spec
        store.update_run(run_id, status="generating_spec")
        _sync_job_status(run_id, "running", phase="generating_spec")
        spec_content = agent.generate_spec()
        store.update_run(run_id, spec_content=spec_content)
        logger.info("Spec generated for run %s (%d chars)", run_id, len(spec_content))

        with httpx.Client() as client:
            # Phase 2: Product analysis
            repo_path = _run_product_analysis(client, agent, store, run_id, spec_content)
            if repo_path is None:
                return  # status already set to failed

            # Phase 3: SE team build
            success = _run_se_team(client, agent, store, run_id, repo_path)
            if success:
                store.update_run(run_id, status="completed")
                _sync_job_status(run_id, "completed", phase="completed")
                logger.info("Founder workflow completed successfully: run_id=%s", run_id)

    except Exception as exc:
        logger.exception("Founder workflow crashed: run_id=%s", run_id)
        store.update_run(run_id, status="failed", error=str(exc)[:1000])
        _sync_job_status(run_id, "failed", error=str(exc)[:500])
