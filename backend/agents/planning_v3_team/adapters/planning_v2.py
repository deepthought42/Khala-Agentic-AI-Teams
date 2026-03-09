"""
Adapter to call the Software Engineering API's Planning V2 workflow.

Verified paths (software_engineering_team.api.main):
- POST /api/software-engineering/planning-v2/run -> { job_id }
- GET  /api/software-engineering/planning-v2/status/{job_id} -> status, current_phase, progress, ...
- GET  /api/software-engineering/planning-v2/result/{job_id} -> phase results, artifacts
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
POLL_INTERVAL = 5.0
MAX_POLL_WAIT = 7200.0


def _se_base_url() -> str:
    return (
        os.environ.get("PLANNING_V3_SOFTWARE_ENGINEERING_URL")
        or os.environ.get("UNIFIED_API_BASE_URL")
        or "http://localhost:8080"
    ).rstrip("/")


def run_planning_v2(
    spec_content: str,
    repo_path: str,
    inspiration_content: Optional[str] = None,
) -> Optional[str]:
    """
    Start Planning V2 workflow. Returns job_id or None on failure.
    """
    base = _se_base_url()
    url = f"{base}/api/software-engineering/planning-v2/run"
    payload: Dict[str, Any] = {
        "spec_content": spec_content,
        "repo_path": repo_path,
    }
    if inspiration_content is not None:
        payload["inspiration_content"] = inspiration_content
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("job_id")
    except (httpx.HTTPError, httpx.TimeoutException, ValueError, KeyError) as e:
        logger.warning("Planning V2 run failed: %s", e)
        return None


def get_planning_v2_status(job_id: str) -> Optional[Dict[str, Any]]:
    """Get status of a planning-v2 job. Returns None on failure."""
    base = _se_base_url()
    url = f"{base}/api/software-engineering/planning-v2/status/{job_id}"
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()
    except (httpx.HTTPError, httpx.TimeoutException, ValueError) as e:
        logger.warning("Planning V2 status failed for %s: %s", job_id, e)
        return None


def get_planning_v2_result(job_id: str) -> Optional[Dict[str, Any]]:
    """Get result of a completed planning-v2 job (phase results, artifacts). Returns None on failure."""
    base = _se_base_url()
    url = f"{base}/api/software-engineering/planning-v2/result/{job_id}"
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()
    except (httpx.HTTPError, httpx.TimeoutException, ValueError) as e:
        logger.warning("Planning V2 result failed for %s: %s", job_id, e)
        return None


def wait_for_planning_v2_completion(
    job_id: str,
    poll_interval: float = POLL_INTERVAL,
    max_wait: float = MAX_POLL_WAIT,
) -> Dict[str, Any]:
    """
    Poll status until completed or failed. Returns final status dict.
    """
    start = time.monotonic()
    while (time.monotonic() - start) < max_wait:
        status = get_planning_v2_status(job_id)
        if status is None:
            return {"status": "failed", "error": "Failed to get status"}
        s = status.get("status", "")
        if s == "completed":
            return status
        if s == "failed":
            return status
        time.sleep(poll_interval)
    return {"status": "failed", "error": "Timed out waiting for Planning V2"}
