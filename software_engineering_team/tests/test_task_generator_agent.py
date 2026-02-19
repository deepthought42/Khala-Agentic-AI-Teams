"""Tests for Task Generator agent."""

from unittest.mock import MagicMock

import pytest

from planning_team.task_generator_agent import TaskGeneratorAgent, TaskGeneratorInput
from shared.models import ProductRequirements, TaskAssignment
from shared.task_parsing import parse_assignment_from_data


@pytest.fixture
def requirements() -> ProductRequirements:
    return ProductRequirements(
        title="Task Manager",
        description="REST API for tasks",
        acceptance_criteria=["CRUD for tasks"],
        constraints=[],
        priority="medium",
    )


@pytest.fixture
def mock_llm() -> MagicMock:
    """LLM returning valid task plan (matches DummyLLMClient pattern)."""
    llm = MagicMock()
    llm.complete_json.return_value = {
        "spec_clarification_needed": False,
        "tasks": [
            {
                "id": "git-setup",
                "title": "Initialize Git Development Branch",
                "type": "git_setup",
                "description": "Create the development branch from main. Ensure the branch exists and is checked out. Verify git status is clean with no uncommitted changes. This enables all feature branches to be created from a stable base.",
                "user_story": "As a developer, I want a dev branch so that I can work on features.",
                "assignee": "devops",
                "requirements": "Create development branch from main. Checkout. Verify clean status.",
                "acceptance_criteria": ["Branch exists", "Clean status", "Created from main"],
                "dependencies": [],
            },
            {
                "id": "backend-tasks-api",
                "title": "Tasks CRUD API",
                "type": "backend",
                "description": "Implement REST API for tasks with GET, POST, PUT, DELETE endpoints. Use FastAPI APIRouter at /api/tasks. Create Pydantic models for request/response. Include pagination and filtering. Return 201 on create, 404 on not found, 422 on validation error.",
                "user_story": "As an API consumer, I want task CRUD so that I can manage tasks.",
                "assignee": "backend",
                "requirements": "FastAPI router, Pydantic models, pagination, filtering.",
                "acceptance_criteria": ["GET returns 200", "POST creates task", "PUT updates", "DELETE removes"],
                "dependencies": ["git-setup"],
            },
        ],
        "execution_order": ["git-setup", "backend-tasks-api"],
        "rationale": "Minimal plan for task manager.",
        "summary": "2 tasks.",
        "requirement_task_mapping": [{"spec_item": "CRUD for tasks", "task_ids": ["backend-tasks-api"]}],
        "clarification_questions": [],
    }
    return llm


def test_task_generator_returns_valid_assignment(
    requirements: ProductRequirements,
    mock_llm: MagicMock,
) -> None:
    """Task Generator returns dict that parses to TaskAssignment."""
    agent = TaskGeneratorAgent(llm_client=mock_llm)
    merged = '{"data_entities":[{"name":"Task"}],"api_endpoints":[],"total_deliverable_count":1,"summary":"Tasks API"}'
    result = agent.run(
        TaskGeneratorInput(
            requirements=requirements,
            merged_spec_analysis=merged,
            codebase_analysis="",
            spec_content_truncated="",
            existing_codebase="",
        )
    )
    assert "tasks" in result
    assert "execution_order" in result
    assignment = parse_assignment_from_data(result)
    assert isinstance(assignment, TaskAssignment)
    assert len(assignment.tasks) >= 1
    assert assignment.execution_order


def test_task_generator_respects_spec_clarification(
    requirements: ProductRequirements,
) -> None:
    """When LLM returns spec_clarification_needed, pass through without validation."""
    llm = MagicMock()
    llm.complete_json.return_value = {
        "spec_clarification_needed": True,
        "clarification_questions": ["What auth method?"],
        "summary": "Spec unclear.",
        "tasks": [],
        "execution_order": [],
    }
    agent = TaskGeneratorAgent(llm_client=llm)
    result = agent.run(
        TaskGeneratorInput(
            requirements=requirements,
            merged_spec_analysis="{}",
        )
    )
    assert result["spec_clarification_needed"] is True
    assert "clarification_questions" in result
