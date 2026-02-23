"""Tests for Tech Lead agent."""

from unittest.mock import MagicMock, patch

import pytest

from planning_team.task_generator_agent.agent import ESCALATION_KEY
from tech_lead_agent import TechLeadAgent, TechLeadInput
from shared.llm import DummyLLMClient
from shared.models import ProductRequirements, SystemArchitecture


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
def architecture() -> SystemArchitecture:
    return SystemArchitecture(
        overview="API + WebApp",
        components=[],
    )


def test_tech_lead_assigns_tasks(requirements: ProductRequirements, architecture: SystemArchitecture) -> None:
    """Tech Lead returns TaskAssignment with tasks and execution order."""
    llm = DummyLLMClient()
    agent = TechLeadAgent(llm_client=llm)
    result = agent.run(TechLeadInput(requirements=requirements, architecture=architecture))
    assert len(result.assignment.tasks) >= 1
    assert result.assignment.execution_order
    assert all(
        t.id in result.assignment.execution_order
        for t in result.assignment.tasks
    )


def test_tech_lead_tasks_have_assignees(requirements: ProductRequirements, architecture: SystemArchitecture) -> None:
    """Each task has an assignee."""
    llm = DummyLLMClient()
    agent = TechLeadAgent(llm_client=llm)
    result = agent.run(TechLeadInput(requirements=requirements, architecture=architecture))
    for task in result.assignment.tasks:
        assert task.assignee
        assert task.description or task.id


# ---------------------------------------------------------------------------
# Escalation handling tests
# ---------------------------------------------------------------------------


def _valid_task_plan(**overrides):
    """Build a minimal valid task plan dict."""
    base = {
        "spec_clarification_needed": False,
        "tasks": [
            {
                "id": "git-setup",
                "title": "Initialize Git",
                "type": "git_setup",
                "description": "Create development branch. Ensure clean status.",
                "user_story": "As a dev, I want a dev branch.",
                "assignee": "devops",
                "requirements": "Create dev branch.",
                "acceptance_criteria": ["Branch exists"],
                "dependencies": [],
            },
        ],
        "execution_order": ["git-setup"],
        "rationale": "Plan.",
        "summary": "1 task.",
        "requirement_task_mapping": [],
        "clarification_questions": [],
    }
    base.update(overrides)
    return base


# Minimal template output so Backend/Frontend planning agents (which use complete_text) get nodes.
_PLANNING_TEMPLATE_RESPONSE = """## NODES ##
id: backend-dummy
domain: backend
kind: task
summary: Dummy backend task
details: Placeholder for tests.
---
## END NODES ##
## EDGES ##
## END EDGES ##
## SUMMARY ##
Dummy plan for tests.
## END SUMMARY ##
"""


def test_tech_lead_handles_escalation_with_refinement(
    requirements: ProductRequirements,
    architecture: SystemArchitecture,
) -> None:
    """When Task Generator returns an escalation payload, Tech Lead refines and retries."""
    llm = MagicMock()
    llm.get_max_context_tokens.return_value = 16384
    llm.complete_text.return_value = _PLANNING_TEMPLATE_RESPONSE

    call_count = 0

    def _complete_json_side_effect(prompt, **kwargs):
        nonlocal call_count
        call_count += 1
        if "Break each acceptance criterion" in prompt:
            return {"refined_criteria": ["Sub-AC-1", "Sub-AC-2"]}
        return _valid_task_plan()

    llm.complete_json.side_effect = _complete_json_side_effect

    escalation_payload = {
        ESCALATION_KEY: True,
        "failed_scopes": [
            {
                "title": "Task Manager",
                "acceptance_criteria": ["CRUD for tasks"],
                "description": "REST API for tasks",
            },
        ],
        "max_depth_reached": 7,
        "parse_errors": ["Truncated JSON"],
        "successful_tasks": [
            {
                "id": "existing-ok",
                "title": "Already generated",
                "type": "backend",
                "description": "This was generated before escalation.",
                "user_story": "Story.",
                "assignee": "backend",
                "requirements": "Req.",
                "acceptance_criteria": ["Done"],
                "dependencies": [],
            },
        ],
        "successful_execution_order": ["existing-ok"],
    }

    agent = TechLeadAgent(llm_client=llm)

    with patch.object(
        agent, "_analyze_spec_chunked", return_value="spec analysis"
    ), patch.object(
        agent, "_analyze_codebase", return_value="codebase analysis"
    ):
        from planning_team.task_generator_agent import TaskGeneratorAgent

        orig_run = TaskGeneratorAgent.run

        first_call = [True]

        def _patched_run(self_tg, input_data, **kwargs):
            if first_call[0]:
                first_call[0] = False
                return escalation_payload
            return orig_run(self_tg, input_data, **kwargs)

        with patch.object(TaskGeneratorAgent, "run", _patched_run):
            result = agent.run(TechLeadInput(
                requirements=requirements,
                architecture=architecture,
            ))

    assert result.assignment is not None
    task_ids = [t.id for t in result.assignment.tasks]
    assert len(task_ids) >= 1


def test_tech_lead_escalation_no_failed_scopes_returns_successful_tasks(
    requirements: ProductRequirements,
    architecture: SystemArchitecture,
) -> None:
    """When escalation has no failed_scopes, successful tasks are returned directly."""
    llm = MagicMock()
    llm.get_max_context_tokens.return_value = 16384
    llm.complete_text.return_value = _PLANNING_TEMPLATE_RESPONSE
    llm.complete_json.return_value = _valid_task_plan()

    escalation_payload = {
        ESCALATION_KEY: True,
        "failed_scopes": [],
        "max_depth_reached": 3,
        "parse_errors": [],
        "successful_tasks": [
            {
                "id": "partial-task",
                "title": "Partial",
                "type": "backend",
                "description": "Details.",
                "user_story": "Story.",
                "assignee": "backend",
                "requirements": "Req.",
                "acceptance_criteria": ["Done"],
                "dependencies": [],
            },
        ],
        "successful_execution_order": ["partial-task"],
    }

    agent = TechLeadAgent(llm_client=llm)

    with patch.object(
        agent, "_analyze_spec_chunked", return_value="spec analysis"
    ), patch.object(
        agent, "_analyze_codebase", return_value="codebase analysis"
    ):
        from planning_team.task_generator_agent import TaskGeneratorAgent

        first_call = [True]

        def _patched_run(self_tg, input_data, **kwargs):
            if first_call[0]:
                first_call[0] = False
                return escalation_payload
            return _valid_task_plan()

        with patch.object(TaskGeneratorAgent, "run", _patched_run):
            result = agent.run(TechLeadInput(
                requirements=requirements,
                architecture=architecture,
            ))

    assert result.assignment is not None
    task_ids = [t.id for t in result.assignment.tasks]
    assert "partial-task" in task_ids


def test_refine_failed_scope_criteria_returns_list(
    requirements: ProductRequirements,
) -> None:
    """_refine_failed_scope_criteria returns a list of refined criteria from LLM."""
    llm = MagicMock()
    llm.get_max_context_tokens.return_value = 16384
    llm.complete_json.return_value = {
        "refined_criteria": ["Sub-1", "Sub-2", "Sub-3"],
    }
    agent = TechLeadAgent(llm_client=llm)
    result = agent._refine_failed_scope_criteria(
        "My Feature", "Description", ["Broad criterion"],
    )
    assert result == ["Sub-1", "Sub-2", "Sub-3"]


def test_refine_failed_scope_criteria_fallback_on_error(
    requirements: ProductRequirements,
) -> None:
    """On LLM failure, _refine_failed_scope_criteria returns original criteria."""
    llm = MagicMock()
    llm.get_max_context_tokens.return_value = 16384
    llm.complete_json.side_effect = Exception("LLM offline")
    agent = TechLeadAgent(llm_client=llm)
    original = ["Original criterion"]
    result = agent._refine_failed_scope_criteria("Title", "Desc", original)
    assert result == original
