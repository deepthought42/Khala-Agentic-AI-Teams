"""
Unit tests for the backend-code-v2 team: models, phases, tool agents, orchestrator.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

import sys
_team_dir = Path(__file__).resolve().parent.parent
if str(_team_dir) not in sys.path:
    sys.path.insert(0, str(_team_dir))

from backend_code_v2_team.models import (
    BackendCodeV2WorkflowResult,
    DeliverResult,
    ExecutionResult,
    Microtask,
    MicrotaskStatus,
    Phase,
    PlanningResult,
    ProblemSolvingResult,
    ReviewIssue,
    ReviewResult,
    ToolAgentInput,
    ToolAgentKind,
    ToolAgentOutput,
)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestModels:
    def test_microtask_defaults(self):
        mt = Microtask(id="mt-1")
        assert mt.status == MicrotaskStatus.PENDING
        assert mt.tool_agent == ToolAgentKind.GENERAL
        assert mt.depends_on == []
        assert mt.output_files == {}

    def test_planning_result_defaults(self):
        pr = PlanningResult()
        assert pr.language == "python"
        assert pr.microtasks == []

    def test_workflow_result_defaults(self):
        wr = BackendCodeV2WorkflowResult()
        assert not wr.success
        assert wr.current_phase == Phase.PLANNING
        assert wr.iterations_used == 0

    def test_review_issue_model(self):
        issue = ReviewIssue(
            source="qa",
            severity="high",
            description="Missing error handler",
            file_path="app/main.py",
        )
        assert issue.severity == "high"

    def test_tool_agent_io(self):
        mt = Microtask(id="mt-test", description="test")
        inp = ToolAgentInput(microtask=mt, repo_path="/tmp/repo", language="java")
        assert inp.language == "java"
        out = ToolAgentOutput(files={"a.java": "class A {}"}, summary="done")
        assert out.success


# ---------------------------------------------------------------------------
# Planning phase tests
# ---------------------------------------------------------------------------

class TestPlanningPhase:
    def test_language_detection_python(self, tmp_path):
        from backend_code_v2_team.phases.planning import _detect_language
        from shared.models import Task, TaskStatus, TaskType

        (tmp_path / "requirements.txt").write_text("flask")
        task = Task(id="t1", type=TaskType.BACKEND, assignee="backend-code-v2", status=TaskStatus.PENDING, description="build api")
        assert _detect_language(tmp_path, task) == "python"

    def test_language_detection_java(self, tmp_path):
        from backend_code_v2_team.phases.planning import _detect_language
        from shared.models import Task, TaskStatus, TaskType

        (tmp_path / "pom.xml").write_text("<project/>")
        task = Task(id="t1", type=TaskType.BACKEND, assignee="backend-code-v2", status=TaskStatus.PENDING, description="build api")
        assert _detect_language(tmp_path, task) == "java"

    def test_language_detection_from_description(self, tmp_path):
        from backend_code_v2_team.phases.planning import _detect_language
        from shared.models import Task, TaskStatus, TaskType

        task = Task(id="t1", type=TaskType.BACKEND, assignee="backend-code-v2", status=TaskStatus.PENDING, description="Use Spring Boot and Java")
        assert _detect_language(tmp_path, task) == "java"

    def test_parse_planning_output(self):
        from backend_code_v2_team.phases.planning import _parse_planning_output

        raw = {
            "microtasks": [
                {"id": "mt-1", "title": "Create models", "tool_agent": "data_engineering", "description": "define models"},
                {"id": "mt-2", "title": "Create API", "tool_agent": "api_openapi", "description": "routes", "depends_on": ["mt-1"]},
            ],
            "language": "python",
            "summary": "Plan created",
        }
        result = _parse_planning_output(raw, "python")
        assert len(result.microtasks) == 2
        assert result.microtasks[0].tool_agent == ToolAgentKind.DATA_ENGINEERING
        assert result.microtasks[1].depends_on == ["mt-1"]

    def test_run_planning_fallback(self, tmp_path):
        from backend_code_v2_team.phases.planning import run_planning
        from shared.models import Task, TaskStatus, TaskType

        mock_llm = MagicMock()
        mock_llm.complete_text.return_value = (
            "## MICROTASKS ##\n## END MICROTASKS ##\n"
            "## LANGUAGE ##\npython\n## END LANGUAGE ##\n"
            "## SUMMARY ##\nempty\n## END SUMMARY ##"
        )
        task = Task(id="t1", type=TaskType.BACKEND, assignee="backend-code-v2", status=TaskStatus.PENDING, description="build something")
        result = run_planning(llm=mock_llm, task=task, repo_path=tmp_path)
        assert len(result.microtasks) == 1
        assert result.microtasks[0].id == "mt-implement-task"


# ---------------------------------------------------------------------------
# Execution phase tests
# ---------------------------------------------------------------------------

class TestExecutionPhase:
    def test_run_execution_with_tool_runners(self, tmp_path):
        from backend_code_v2_team.phases.execution import run_execution
        from shared.models import Task, TaskStatus, TaskType

        mock_llm = MagicMock()
        task = Task(id="t1", type=TaskType.BACKEND, assignee="backend-code-v2", status=TaskStatus.PENDING, description="build")

        def fake_runner(inp):
            return ToolAgentOutput(files={"models.py": "class User: pass"}, summary="done")

        planning = PlanningResult(
            microtasks=[Microtask(id="mt-1", tool_agent=ToolAgentKind.DATA_ENGINEERING, description="models")],
            language="python",
        )
        result = run_execution(
            llm=mock_llm,
            task=task,
            planning_result=planning,
            repo_path=tmp_path,
            tool_runners={ToolAgentKind.DATA_ENGINEERING: fake_runner},
        )
        assert "models.py" in result.files
        assert result.microtasks[0].status == MicrotaskStatus.COMPLETED

    def test_run_execution_general_fallback(self, tmp_path):
        from backend_code_v2_team.phases.execution import run_execution
        from shared.models import Task, TaskStatus, TaskType

        mock_llm = MagicMock()
        mock_llm.complete_text.return_value = (
            "## FILE app.py ##\nprint('hello')\n## SUMMARY ##\ndone\n## END SUMMARY ##"
        )
        task = Task(id="t1", type=TaskType.BACKEND, assignee="backend-code-v2", status=TaskStatus.PENDING, description="build")
        planning = PlanningResult(
            microtasks=[Microtask(id="mt-gen", tool_agent=ToolAgentKind.GENERAL, description="general task")],
            language="python",
        )
        result = run_execution(llm=mock_llm, task=task, planning_result=planning, repo_path=tmp_path)
        assert "app.py" in result.files


# ---------------------------------------------------------------------------
# Review phase tests
# ---------------------------------------------------------------------------

class TestReviewPhase:
    def test_review_passes_no_issues(self, tmp_path):
        from backend_code_v2_team.phases.review import run_review
        from shared.models import Task, TaskStatus, TaskType

        mock_llm = MagicMock()
        mock_llm.complete_text.return_value = (
            "## PASSED ##\ntrue\n## END PASSED ##\n"
            "## ISSUES ##\n## END ISSUES ##\n"
            "## SUMMARY ##\nall good\n## END SUMMARY ##"
        )
        task = Task(id="t1", type=TaskType.BACKEND, assignee="backend-code-v2", status=TaskStatus.PENDING, description="build")
        exec_result = ExecutionResult(files={"app.py": "print()"}, microtasks=[])
        result = run_review(llm=mock_llm, task=task, execution_result=exec_result, repo_path=tmp_path)
        assert result.passed
        assert result.build_ok

    def test_review_fails_on_critical_issues(self, tmp_path):
        from backend_code_v2_team.phases.review import run_review
        from shared.models import Task, TaskStatus, TaskType

        mock_llm = MagicMock()
        mock_llm.complete_text.return_value = (
            "## PASSED ##\nfalse\n## END PASSED ##\n"
            "## ISSUES ##\n---\nsource: code_review\nseverity: critical\ndescription: SQL injection\nfile_path: \nrecommendation: \n---\n## END ISSUES ##\n"
            "## SUMMARY ##\ncritical issue\n## END SUMMARY ##"
        )
        task = Task(id="t1", type=TaskType.BACKEND, assignee="backend-code-v2", status=TaskStatus.PENDING, description="build")
        exec_result = ExecutionResult(files={"app.py": "query(input)"}, microtasks=[])
        result = run_review(llm=mock_llm, task=task, execution_result=exec_result, repo_path=tmp_path)
        assert not result.passed


# ---------------------------------------------------------------------------
# Problem-solving phase tests
# ---------------------------------------------------------------------------

class TestProblemSolvingPhase:
    def test_no_actionable_issues(self):
        from backend_code_v2_team.phases.problem_solving import run_problem_solving
        from shared.models import Task, TaskStatus, TaskType

        mock_llm = MagicMock()
        task = Task(id="t1", type=TaskType.BACKEND, assignee="backend-code-v2", status=TaskStatus.PENDING, description="build")
        review = ReviewResult(passed=False, issues=[
            ReviewIssue(source="code_review", severity="info", description="minor style"),
        ])
        result = run_problem_solving(llm=mock_llm, task=task, review_result=review, current_files={"a.py": "pass"})
        assert result.resolved

    def test_applies_fixes(self):
        from backend_code_v2_team.phases.problem_solving import run_problem_solving
        from shared.models import Task, TaskStatus, TaskType

        mock_llm = MagicMock()
        mock_llm.complete_text.return_value = (
            "## FILE a.py ##\nfixed_code()\n"
            "## FIXES_APPLIED ##\n---\nissue: bug\nfix: fixed\n---\n## END FIXES_APPLIED ##\n"
            "## RESOLVED ##\ntrue\n## END RESOLVED ##\n"
            "## SUMMARY ##\nFixed bug\n## END SUMMARY ##"
        )
        task = Task(id="t1", type=TaskType.BACKEND, assignee="backend-code-v2", status=TaskStatus.PENDING, description="build")
        review = ReviewResult(passed=False, issues=[
            ReviewIssue(source="code_review", severity="high", description="null pointer"),
        ])
        result = run_problem_solving(llm=mock_llm, task=task, review_result=review, current_files={"a.py": "bad_code()"})
        assert result.resolved
        assert result.files["a.py"] == "fixed_code()"


# ---------------------------------------------------------------------------
# Tool agents tests
# ---------------------------------------------------------------------------

class TestToolAgents:
    def test_data_engineering_agent(self):
        from backend_code_v2_team.tool_agents.data_engineering import DataEngineeringToolAgent

        mock_llm = MagicMock()
        mock_llm.complete_text.return_value = (
            "## FILE models.py ##\nclass User: pass\n## SUMMARY ##\nschema done\n## END SUMMARY ##"
        )
        agent = DataEngineeringToolAgent(mock_llm)
        inp = ToolAgentInput(microtask=Microtask(id="mt-1", description="create schema"), language="python")
        out = agent.run(inp)
        assert "models.py" in out.files

    def test_api_openapi_agent(self):
        from backend_code_v2_team.tool_agents.api_openapi import ApiOpenApiToolAgent

        mock_llm = MagicMock()
        mock_llm.complete_text.return_value = (
            "## FILE routes.py ##\nroute()\n## SUMMARY ##\napi done\n## END SUMMARY ##"
        )
        agent = ApiOpenApiToolAgent(mock_llm)
        inp = ToolAgentInput(microtask=Microtask(id="mt-1", description="create endpoint"), language="python")
        out = agent.run(inp)
        assert "routes.py" in out.files

    def test_auth_agent(self):
        from backend_code_v2_team.tool_agents.auth import AuthToolAgent

        mock_llm = MagicMock()
        mock_llm.complete_text.return_value = (
            "## FILE auth.py ##\ndef login(): pass\n## SUMMARY ##\nauth done\n## END SUMMARY ##"
        )
        agent = AuthToolAgent(mock_llm)
        inp = ToolAgentInput(microtask=Microtask(id="mt-1", description="add login"), language="python")
        out = agent.run(inp)
        assert "auth.py" in out.files

    def test_cicd_stub(self):
        from backend_code_v2_team.tool_agents.cicd import CicdAdapterAgent

        agent = CicdAdapterAgent()
        inp = ToolAgentInput(microtask=Microtask(id="mt-1", description="cicd"), language="python")
        out = agent.run(inp)
        assert not out.files
        assert out.summary

    def test_containerization_stub(self):
        from backend_code_v2_team.tool_agents.containerization import ContainerizationAdapterAgent

        agent = ContainerizationAdapterAgent()
        inp = ToolAgentInput(microtask=Microtask(id="mt-1", description="docker"), language="python")
        out = agent.run(inp)
        assert not out.files
        assert out.summary


# ---------------------------------------------------------------------------
# Orchestrator (BackendCodeV2TeamLead) tests
# ---------------------------------------------------------------------------

class TestBackendCodeV2TeamLead:
    def test_read_repo_code(self, tmp_path):
        from backend_code_v2_team.orchestrator import BackendCodeV2TeamLead

        (tmp_path / "app.py").write_text("print('hello')")
        (tmp_path / "readme.md").write_text("# Readme")  # not a tracked extension by default in our reader
        code = BackendCodeV2TeamLead._read_repo_code(tmp_path)
        assert "app.py" in code
        assert "print('hello')" in code

    def test_build_tool_runners(self):
        from backend_code_v2_team.orchestrator import BackendCodeV2TeamLead

        mock_llm = MagicMock()
        lead = BackendCodeV2TeamLead(mock_llm)
        runners = lead._build_tool_runners()
        assert ToolAgentKind.DATA_ENGINEERING in runners
        assert ToolAgentKind.API_OPENAPI in runners
        assert ToolAgentKind.AUTH in runners

    def test_run_workflow_no_files_produced(self, tmp_path):
        """When execution produces no files, workflow should fail gracefully."""
        from backend_code_v2_team.orchestrator import BackendCodeV2TeamLead
        from shared.models import Task, TaskStatus, TaskType

        mock_llm = MagicMock()
        planning_response = (
            "## MICROTASKS ##\n---\nid: mt-1\ntitle: A\ndescription: a\ntool_agent: general\ndepends_on: \n---\n## END MICROTASKS ##\n"
            "## LANGUAGE ##\npython\n## END LANGUAGE ##\n## SUMMARY ##\nplan\n## END SUMMARY ##"
        )
        execution_response = "## SUMMARY ##\nnothing\n## END SUMMARY ##"
        mock_llm.complete_text.side_effect = [planning_response, execution_response]

        lead = BackendCodeV2TeamLead(mock_llm)
        task = Task(id="t-test", type=TaskType.BACKEND, assignee="backend-code-v2", status=TaskStatus.PENDING, description="Do something")

        (tmp_path / ".git").mkdir()

        result = lead.run_workflow(repo_path=tmp_path, task=task)
        assert not result.success
        assert "no files" in result.failure_reason.lower() or result.failure_reason != ""
