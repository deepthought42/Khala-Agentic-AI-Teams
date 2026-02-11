"""Tests for the run-team API endpoint."""

import subprocess
import tempfile
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
    """Create a minimal valid git repo with initial_spec.md."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "initial_spec.md").write_text("# Task Manager API\n\nREST API for tasks.")
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
    r = client.post("/run-team", json={"repo_path": "/nonexistent/path", "use_llm_for_spec": False})
    assert r.status_code == 400


def test_run_team_success(client: TestClient, temp_repo: Path) -> None:
    """run-team completes with valid repo (uses DummyLLM by default)."""
    r = client.post("/run-team", json={"repo_path": str(temp_repo), "use_llm_for_spec": False})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "completed"
    assert "requirements_title" in data
    assert "task_ids" in data
    assert "task_results" in data
