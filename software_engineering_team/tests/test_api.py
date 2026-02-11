"""Tests for the run-team API endpoint."""

import os
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure path setup before importing api
import sys
_team_dir = Path(__file__).resolve().parent.parent
if str(_team_dir) not in sys.path:
    sys.path.insert(0, str(_team_dir))

from api.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    """Create a minimal valid git repo with initial_spec.md and initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "initial_spec.md").write_text("# Task Manager API\n\nREST API for tasks.")
    subprocess.run(
        ["git", "init"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "add", "initial_spec.md"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial spec"],
        cwd=repo,
        capture_output=True,
        check=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@test.com", "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@test.com"},
    )
    return repo


def test_health(client: TestClient) -> None:
    """Health endpoint returns ok."""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_run_team_requires_repo_path(client: TestClient) -> None:
    """run-team returns 422 when repo_path missing."""
    r = client.post("/run-team", json={})
    assert r.status_code == 422


def test_run_team_invalid_path(client: TestClient) -> None:
    """run-team returns 400 for non-existent path."""
    r = client.post("/run-team", json={"repo_path": "/nonexistent/path"})
    assert r.status_code == 400


def test_get_job_status_404(client: TestClient) -> None:
    """GET /run-team/{job_id} returns 404 for unknown job."""
    r = client.get("/run-team/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_run_team_returns_job_id(client: TestClient, temp_repo: Path) -> None:
    """POST /run-team returns job_id and status immediately."""
    r = client.post("/run-team", json={"repo_path": str(temp_repo)})
    assert r.status_code == 200
    data = r.json()
    assert "job_id" in data
    assert data["status"] in ("running", "pending")
    assert "message" in data


def test_run_team_poll_status(client: TestClient, temp_repo: Path) -> None:
    """POST starts job; GET /run-team/{job_id} returns status until completed."""
    r = client.post("/run-team", json={"repo_path": str(temp_repo)})
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    # Brief delay so job file is fully written before first poll
    time.sleep(0.2)

    # Poll until completed or failed (max 60s)
    data = None
    for _ in range(60):
        r = client.get(f"/run-team/{job_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["job_id"] == job_id
        assert data["status"] in ("pending", "running", "completed", "failed")
        if data["status"] in ("completed", "failed"):
            break
        time.sleep(1)

    assert data is not None
    assert data["status"] == "completed"
    assert "requirements_title" in data or data.get("architecture_overview") is not None
    assert "task_results" in data

    # Verify agents wrote files and committed to the repo
    backend_dir = temp_repo / "backend"
    devops_dir = temp_repo / "devops"
    assert backend_dir.exists() or devops_dir.exists(), "Agent output should create backend or devops dirs"
    if backend_dir.exists():
        assert any(backend_dir.rglob("*.py")), "Backend should have added Python files"
    if (temp_repo / ".github" / "workflows").exists():
        assert (temp_repo / ".github" / "workflows" / "ci.yml").exists(), "DevOps should add CI config"
