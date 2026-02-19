"""Unit tests for the DevOps Expert agent."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from devops_agent.agent import DevOpsExpertAgent


def test_devops_run_workflow_calls_plan_task_without_error() -> None:
    """run_workflow calls _plan_task and completes without AttributeError."""
    import subprocess
    import tempfile

    mock_llm = MagicMock()
    mock_llm.get_max_context_tokens.return_value = 16384
    mock_llm.complete_json.side_effect = [
        {"feature_intent": "Containerize", "what_changes": ["Dockerfile"], "algorithms_data_structures": "", "tests_needed": ""},
        {"pipeline_yaml": "", "dockerfile": "FROM node:20", "summary": "Done", "needs_clarification": False, "clarification_requests": []},
    ]
    agent = DevOpsExpertAgent(llm_client=mock_llm)
    build_verifier = MagicMock(return_value=(True, ""))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        (path / "package.json").write_text("{}")
        subprocess.run(["git", "init"], cwd=path, capture_output=True, check=False)
        result = agent.run_workflow(
            repo_path=path,
            task_description="Containerize frontend",
            requirements="Add Dockerfile",
            build_verifier=build_verifier,
            task_id="devops-frontend",
        )
    assert result.success
    assert mock_llm.complete_json.call_count >= 1


def test_devops_plan_task_returns_plan_markdown() -> None:
    """_plan_task parses LLM JSON and returns plan markdown."""
    mock_llm = MagicMock()
    mock_llm.get_max_context_tokens.return_value = 16384
    mock_llm.complete_json.return_value = {
        "feature_intent": "Containerize the backend for build and deploy",
        "what_changes": ["Dockerfile", ".github/workflows/ci.yml"],
        "algorithms_data_structures": "Multi-stage Docker build; non-root user in container",
        "tests_needed": "YAML parse must succeed; docker build must complete",
    }
    agent = DevOpsExpertAgent(llm_client=mock_llm)
    plan_text = agent._plan_task(
        task_description="Containerize and deploy the backend",
        requirements="Add Dockerfile and CI pipeline",
        architecture=None,
        existing_pipeline=None,
        target_repo="backend",
    )
    assert plan_text
    assert "Containerize the backend" in plan_text
    assert "Dockerfile" in plan_text
    assert ".github/workflows/ci.yml" in plan_text
    assert "Multi-stage" in plan_text or "Docker" in plan_text
    assert "docker build" in plan_text or "YAML" in plan_text
