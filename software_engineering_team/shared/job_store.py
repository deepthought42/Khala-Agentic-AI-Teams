"""
Job store for async API: persists job status and progress.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

JOB_STATUS_PENDING = "pending"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"


def _jobs_dir(cache_dir: str | Path = ".agent_cache") -> Path:
    path = Path(cache_dir) / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _job_file(job_id: str, cache_dir: str | Path = ".agent_cache") -> Path:
    return _jobs_dir(cache_dir) / f"{job_id}.json"


def create_job(job_id: str, repo_path: str, cache_dir: str | Path = ".agent_cache") -> None:
    """Create a new job with pending status."""
    data = {
        "job_id": job_id,
        "repo_path": repo_path,
        "status": JOB_STATUS_PENDING,
        "progress": 0,
        "current_task": None,
        "task_results": [],
        "tasks": [],
        "execution_order": [],
        "error": None,
        "architecture_overview": None,
        "requirements_title": None,
    }
    _job_file(job_id, cache_dir).write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_job(job_id: str, cache_dir: str | Path = ".agent_cache") -> Optional[Dict[str, Any]]:
    """Get job data or None if not found."""
    path = _job_file(job_id, cache_dir)
    if not path.exists():
        return None
    for attempt in range(2):
        try:
            raw = path.read_text(encoding="utf-8")
            if not raw.strip():
                if attempt == 0:
                    time.sleep(0.1)
                    continue
                return None
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            if attempt == 0:
                time.sleep(0.1)
                continue
            logger.warning("Failed to read job %s: %s", job_id, e)
            return None
        except Exception as e:
            logger.warning("Failed to read job %s: %s", job_id, e)
            return None
    return None


def update_job(
    job_id: str,
    cache_dir: str | Path = ".agent_cache",
    **kwargs: Any,
) -> None:
    """Update job fields. Merges with existing data."""
    data = get_job(job_id, cache_dir) or {}
    data.update(kwargs)
    _job_file(job_id, cache_dir).write_text(json.dumps(data, indent=2), encoding="utf-8")


def add_task_result(job_id: str, result: Dict[str, Any], cache_dir: str | Path = ".agent_cache") -> None:
    """Append a task result to the job."""
    data = get_job(job_id, cache_dir) or {}
    results = data.get("task_results", [])
    results.append(result)
    data["task_results"] = results
    _job_file(job_id, cache_dir).write_text(json.dumps(data, indent=2), encoding="utf-8")
