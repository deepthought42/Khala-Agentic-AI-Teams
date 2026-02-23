"""Tests for Task Generator agent."""

from unittest.mock import MagicMock, patch

import pytest

from planning_team.task_generator_agent import ESCALATION_KEY, TaskGeneratorAgent, TaskGeneratorInput
from shared.llm import LLMJsonParseError
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
    llm.get_max_context_tokens.return_value = 16384
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
    llm.get_max_context_tokens.return_value = 16384
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


def test_task_generator_includes_open_questions_in_context(
    requirements: ProductRequirements,
    mock_llm: MagicMock,
) -> None:
    """Open questions from Spec Intake are included in the prompt context."""
    agent = TaskGeneratorAgent(llm_client=mock_llm)
    merged = '{"data_entities":[{"name":"Task"}],"api_endpoints":[],"total_deliverable_count":1}'
    agent.run(
        TaskGeneratorInput(
            requirements=requirements,
            merged_spec_analysis=merged,
            open_questions=["What is the target availability SLA for the API?"],
            assumptions=["Assume JWT auth"],
        )
    )
    call_args = mock_llm.complete_json.call_args
    assert call_args is not None
    prompt = call_args[0][0]
    assert "OPEN QUESTIONS" in prompt
    assert "target availability SLA" in prompt
    assert "Assumptions from Spec Intake" in prompt
    assert "JWT auth" in prompt


def test_task_generator_tolerates_resolved_questions_in_output(
    requirements: ProductRequirements,
) -> None:
    """When LLM returns resolved_questions, parsing and validation still succeed."""
    llm = MagicMock()
    llm.get_max_context_tokens.return_value = 16384
    llm.complete_json.return_value = {
        "spec_clarification_needed": False,
        "tasks": [
            {
                "id": "git-setup",
                "title": "Initialize Git",
                "type": "git_setup",
                "description": "Create development branch. Ensure clean status. Verify branch exists.",
                "user_story": "As a developer, I want a dev branch.",
                "assignee": "devops",
                "requirements": "Create dev branch.",
                "acceptance_criteria": ["Branch exists", "Clean status", "From main"],
                "dependencies": [],
            },
            {
                "id": "devops-sla-monitoring",
                "title": "Define SLOs and monitoring for API availability",
                "type": "devops",
                "description": "Implement metrics and alerts for 99.9% availability target. Configure health checks and escalation.",
                "user_story": "As an operator, I want SLO monitoring so that we meet availability targets.",
                "assignee": "devops",
                "requirements": "SLO definitions, metrics, alerts, runbooks.",
                "acceptance_criteria": ["SLOs documented", "Alerts configured", "Runbook exists"],
                "dependencies": ["git-setup"],
            },
        ],
        "execution_order": ["git-setup", "devops-sla-monitoring"],
        "rationale": "Plan with SLA resolution.",
        "summary": "2 tasks including SLA monitoring.",
        "requirement_task_mapping": [{"spec_item": "CRUD for tasks", "task_ids": ["devops-sla-monitoring"]}],
        "clarification_questions": [],
        "resolved_questions": [
            {
                "question": "What is the target availability SLA?",
                "category": "sla-availability",
                "decision": "99.9% with multi-AZ and error budget",
                "justification": "Cost-sensitive default for customer-facing API; aligns with typical cloud managed service SLAs.",
                "linked_task_ids": ["devops-sla-monitoring"],
            },
        ],
    }
    agent = TaskGeneratorAgent(llm_client=llm)
    result = agent.run(
        TaskGeneratorInput(
            requirements=requirements,
            merged_spec_analysis='{"data_entities":[],"total_deliverable_count":1}',
            open_questions=["What is the target availability SLA?"],
        )
    )
    assert "resolved_questions" in result
    resolved = result["resolved_questions"]
    assert len(resolved) == 1
    assert resolved[0]["decision"] == "99.9% with multi-AZ and error budget"
    assert resolved[0]["justification"]
    assert "devops-sla-monitoring" in resolved[0]["linked_task_ids"]
    assignment = parse_assignment_from_data(result)
    assert len(assignment.tasks) == 2


# ---------------------------------------------------------------------------
# Recursive microtask decomposition tests
# ---------------------------------------------------------------------------


def _make_valid_response(**overrides):
    """Helper: build a minimal valid LLM task-plan response."""
    base = {
        "spec_clarification_needed": False,
        "tasks": [
            {
                "id": "task-1",
                "title": "Do the thing",
                "type": "backend",
                "description": "Implement something useful. Full details included.",
                "user_story": "As a dev, I want this.",
                "assignee": "backend",
                "requirements": "Must work.",
                "acceptance_criteria": ["It works"],
                "dependencies": [],
            },
        ],
        "execution_order": ["task-1"],
        "rationale": "Simple plan.",
        "summary": "1 task.",
        "requirement_task_mapping": [{"spec_item": "AC1", "task_ids": ["task-1"]}],
        "clarification_questions": [],
    }
    base.update(overrides)
    return base


def test_json_parse_error_triggers_decomposition(requirements: ProductRequirements) -> None:
    """When LLM raises LLMJsonParseError, Task Generator decomposes instead of crashing."""
    multi_ac_reqs = requirements.model_copy(
        update={"acceptance_criteria": ["AC-1: login", "AC-2: logout"]},
    )
    llm = MagicMock()
    llm.get_max_context_tokens.return_value = 16384

    call_count = 0

    def _side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise LLMJsonParseError("Truncated", error_kind="json_parse", response_preview="...")
        return _make_valid_response()

    llm.complete_json.side_effect = _side_effect
    agent = TaskGeneratorAgent(llm_client=llm)
    result = agent.run(TaskGeneratorInput(
        requirements=multi_ac_reqs,
        merged_spec_analysis='{"summary":"test"}',
    ))
    assert "tasks" in result
    assert not result.get(ESCALATION_KEY)


def test_non_json_error_does_not_trigger_decomposition(requirements: ProductRequirements) -> None:
    """Non-JSON errors (e.g. HTTP 400) propagate without triggering decomposition."""
    from shared.llm import LLMPermanentError

    llm = MagicMock()
    llm.get_max_context_tokens.return_value = 16384
    llm.complete_json.side_effect = LLMPermanentError("400 Bad Request", status_code=400)

    agent = TaskGeneratorAgent(llm_client=llm)
    with pytest.raises(LLMPermanentError, match="400"):
        agent.run(TaskGeneratorInput(
            requirements=requirements,
            merged_spec_analysis='{"summary":"test"}',
        ))


def test_depth_exhaustion_produces_escalation_payload(requirements: ProductRequirements) -> None:
    """When all decomposition levels fail, an escalation payload is returned."""
    llm = MagicMock()
    llm.get_max_context_tokens.return_value = 16384
    llm.complete_json.side_effect = LLMJsonParseError(
        "Truncated", error_kind="json_parse", response_preview="...",
    )

    single_ac_reqs = requirements.model_copy(
        update={"acceptance_criteria": ["Only one criterion"]},
    )
    agent = TaskGeneratorAgent(llm_client=llm)
    result = agent.run(TaskGeneratorInput(
        requirements=single_ac_reqs,
        merged_spec_analysis='{"summary":"test"}',
    ))

    assert result.get(ESCALATION_KEY) is True
    assert "failed_scopes" in result
    assert isinstance(result["parse_errors"], list)
    assert result["successful_tasks"] == []


def test_recursive_split_merges_successful_branches(requirements: ProductRequirements) -> None:
    """Successful sub-scope results are merged with deduplicated tasks and order."""
    four_ac_reqs = requirements.model_copy(
        update={"acceptance_criteria": ["AC1", "AC2", "AC3", "AC4"]},
    )
    llm = MagicMock()
    llm.get_max_context_tokens.return_value = 16384

    call_count = 0

    def _side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise LLMJsonParseError("Truncated", error_kind="json_parse", response_preview="...")
        task_id = f"task-{call_count}"
        return _make_valid_response(
            tasks=[{
                "id": task_id, "title": f"Task {call_count}", "type": "backend",
                "description": "Details.", "user_story": "Story.",
                "assignee": "backend", "requirements": "Req.",
                "acceptance_criteria": ["Done"], "dependencies": [],
            }],
            execution_order=[task_id],
        )

    llm.complete_json.side_effect = _side_effect
    agent = TaskGeneratorAgent(llm_client=llm)
    result = agent.run(TaskGeneratorInput(
        requirements=four_ac_reqs,
        merged_spec_analysis='{"summary":"test"}',
    ))

    assert not result.get(ESCALATION_KEY)
    task_ids = [t["id"] for t in result["tasks"]]
    assert len(task_ids) == len(set(task_ids)), "Task IDs should be unique"
    assert len(result["execution_order"]) == len(set(result["execution_order"]))


def test_multi_level_recursion_with_mixed_outcomes(requirements: ProductRequirements) -> None:
    """Mixed success/failure across branches: successful tasks preserved, failures escalated."""
    four_ac_reqs = requirements.model_copy(
        update={"acceptance_criteria": ["AC1", "AC2", "AC3", "AC4"]},
    )
    llm = MagicMock()
    llm.get_max_context_tokens.return_value = 16384

    call_count = 0

    def _side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise LLMJsonParseError("Truncated", error_kind="json_parse", response_preview="...")
        return _make_valid_response(
            tasks=[{
                "id": f"ok-{call_count}", "title": f"OK {call_count}", "type": "backend",
                "description": "Fine.", "user_story": "Story.",
                "assignee": "backend", "requirements": "Req.",
                "acceptance_criteria": ["Done"], "dependencies": [],
            }],
            execution_order=[f"ok-{call_count}"],
        )

    llm.complete_json.side_effect = _side_effect
    agent = TaskGeneratorAgent(llm_client=llm)
    result = agent.run(TaskGeneratorInput(
        requirements=four_ac_reqs,
        merged_spec_analysis='{"summary":"test"}',
    ))

    assert "tasks" in result or result.get(ESCALATION_KEY)
    if not result.get(ESCALATION_KEY):
        assert len(result["tasks"]) >= 1
