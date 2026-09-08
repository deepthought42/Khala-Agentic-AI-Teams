"""Tests for the SE Temporal activity wrappers.

Each activity is a thin wrapper around an orchestrator entry point with an
exception-handling outer try/except. The tests cover the happy path (the
wrapped function is called) and the exception path (failure is captured into
the job store via ``update_job``).
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import pytest
from temporalio.common import RetryPolicy


@pytest.fixture(autouse=True)
def _autouse_patched_job_store(patched_job_store):
    return patched_job_store


def _fake_activity_info(attempt: int, maximum_attempts: int = 3):
    return type(
        "I",
        (),
        {"retry_policy": RetryPolicy(maximum_attempts=maximum_attempts), "attempt": attempt},
    )()


def test_retry_failed_activity_success(monkeypatch) -> None:
    from software_engineering_team.temporal import activities

    called: Dict[str, str] = {}

    def fake(job_id, *, trace_id=None):
        called["id"] = job_id
        called["trace_id"] = trace_id

    monkeypatch.setattr("software_engineering_team.orchestrator.run_failed_tasks", fake)
    activities.retry_failed_activity("j1")
    assert called["id"] == "j1"
    assert called["trace_id"]  # activity generates one when the caller passes none


def test_retry_failed_activity_failure(monkeypatch, tmp_path, patched_job_store) -> None:
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("j-fail", repo_path=str(tmp_path))

    def boom(_, **kw):
        raise RuntimeError("retry exploded")

    monkeypatch.setattr("software_engineering_team.orchestrator.run_failed_tasks", boom)
    with pytest.raises(RuntimeError, match="retry exploded"):
        activities.retry_failed_activity("j-fail")
    job = js.get_job("j-fail")
    assert job["status"] == js.JOB_STATUS_FAILED


def test_retry_failed_activity_non_final_attempt_does_not_mark_failed(
    monkeypatch, tmp_path, patched_job_store
) -> None:
    """Mirror of the other activities' non-final-attempt tests for retry_failed_activity."""
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("rf-retry", repo_path=str(tmp_path))

    monkeypatch.setattr(activities.activity, "in_activity", lambda: True)
    monkeypatch.setattr(activities.activity, "info", lambda: _fake_activity_info(attempt=1))

    def boom(_, **kw):
        raise RuntimeError("transient retry failure")

    monkeypatch.setattr("software_engineering_team.orchestrator.run_failed_tasks", boom)
    with pytest.raises(RuntimeError, match="transient retry failure"):
        activities.retry_failed_activity("rf-retry")

    job = js.get_job("rf-retry")
    assert job["status"] != js.JOB_STATUS_FAILED


def test_run_frontend_code_v2_activity_failure(monkeypatch, tmp_path, patched_job_store) -> None:
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("fv2-j", repo_path=str(tmp_path))

    def boom(*a, **kw):
        raise RuntimeError("v2 frontend failed")

    monkeypatch.setattr(activities, "_run_frontend_code_v2_impl", boom)
    with pytest.raises(RuntimeError, match="v2 frontend failed"):
        activities.run_frontend_code_v2_activity("fv2-j", str(tmp_path), {"id": "t1"})
    job = js.get_job("fv2-j")
    assert job["status"] == js.JOB_STATUS_FAILED


def test_run_backend_code_v2_activity_failure(monkeypatch, tmp_path, patched_job_store) -> None:
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("bv2-j", repo_path=str(tmp_path))

    def boom(*a, **kw):
        raise RuntimeError("v2 backend failed")

    monkeypatch.setattr(activities, "_run_backend_code_v2_impl", boom)
    with pytest.raises(RuntimeError, match="v2 backend failed"):
        activities.run_backend_code_v2_activity("bv2-j", str(tmp_path), {"id": "t1"})
    job = js.get_job("bv2-j")
    assert job["status"] == js.JOB_STATUS_FAILED


def test_run_frontend_code_v2_activity_non_final_attempt_does_not_mark_failed(
    monkeypatch, tmp_path, patched_job_store
) -> None:
    """On a non-final Temporal attempt, a transient failure does NOT mark the job
    FAILED (Temporal will retry) — only the final attempt marks it, so a retry
    that later succeeds never leaves a transient FAILED status behind."""
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("fv2-retry", repo_path=str(tmp_path))

    monkeypatch.setattr(activities.activity, "in_activity", lambda: True)
    monkeypatch.setattr(activities.activity, "info", lambda: _fake_activity_info(attempt=1))

    def boom(*a, **kw):
        raise RuntimeError("transient frontend failure")

    monkeypatch.setattr(activities, "_run_frontend_code_v2_impl", boom)
    with pytest.raises(RuntimeError, match="transient frontend failure"):
        activities.run_frontend_code_v2_activity("fv2-retry", str(tmp_path), {"id": "t1"})

    job = js.get_job("fv2-retry")
    assert job["status"] != js.JOB_STATUS_FAILED


def test_run_backend_code_v2_activity_non_final_attempt_does_not_mark_failed(
    monkeypatch, tmp_path, patched_job_store
) -> None:
    """Mirror of the frontend non-final-attempt test for the backend activity."""
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("bv2-retry", repo_path=str(tmp_path))

    monkeypatch.setattr(activities.activity, "in_activity", lambda: True)
    monkeypatch.setattr(activities.activity, "info", lambda: _fake_activity_info(attempt=1))

    def boom(*a, **kw):
        raise RuntimeError("transient backend failure")

    monkeypatch.setattr(activities, "_run_backend_code_v2_impl", boom)
    with pytest.raises(RuntimeError, match="transient backend failure"):
        activities.run_backend_code_v2_activity("bv2-retry", str(tmp_path), {"id": "t1"})

    job = js.get_job("bv2-retry")
    assert job["status"] != js.JOB_STATUS_FAILED


def test_run_product_analysis_activity_failure(monkeypatch, tmp_path, patched_job_store) -> None:
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("pa-j", repo_path=str(tmp_path))

    def boom(*a, **kw):
        raise RuntimeError("PA failed")

    monkeypatch.setattr(activities, "_run_product_analysis_impl", boom)
    with pytest.raises(RuntimeError, match="PA failed"):
        activities.run_product_analysis_activity("pa-j", str(tmp_path), "spec")
    job = js.get_job("pa-j")
    assert job["status"] == js.JOB_STATUS_FAILED


def test_run_product_analysis_activity_non_final_attempt_does_not_mark_failed(
    monkeypatch, tmp_path, patched_job_store
) -> None:
    """Mirror of the frontend/backend non-final-attempt tests for product analysis."""
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("pa-retry", repo_path=str(tmp_path))

    monkeypatch.setattr(activities.activity, "in_activity", lambda: True)
    monkeypatch.setattr(activities.activity, "info", lambda: _fake_activity_info(attempt=1))

    def boom(*a, **kw):
        raise RuntimeError("transient PA failure")

    monkeypatch.setattr(activities, "_run_product_analysis_impl", boom)
    with pytest.raises(RuntimeError, match="transient PA failure"):
        activities.run_product_analysis_activity("pa-retry", str(tmp_path), "spec")

    job = js.get_job("pa-retry")
    assert job["status"] != js.JOB_STATUS_FAILED


def test_run_frontend_code_v2_activity_happy(monkeypatch, tmp_path, patched_job_store) -> None:
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("fv2-ok", repo_path=str(tmp_path))
    called = {}

    def fake_impl(job_id, repo_path, task_dict, arch):
        called["job_id"] = job_id

    monkeypatch.setattr(activities, "_run_frontend_code_v2_impl", fake_impl)
    activities.run_frontend_code_v2_activity("fv2-ok", str(tmp_path), {"id": "t"}, "arch")
    assert called["job_id"] == "fv2-ok"


def test_run_backend_code_v2_activity_happy(monkeypatch, tmp_path, patched_job_store) -> None:
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("bv2-ok", repo_path=str(tmp_path))
    called = {}

    def fake_impl(job_id, repo_path, task_dict, arch):
        called["job_id"] = job_id

    monkeypatch.setattr(activities, "_run_backend_code_v2_impl", fake_impl)
    activities.run_backend_code_v2_activity("bv2-ok", str(tmp_path), {"id": "t"}, "arch")
    assert called["job_id"] == "bv2-ok"


def test_run_product_analysis_activity_happy(monkeypatch, tmp_path, patched_job_store) -> None:
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("pa-ok", repo_path=str(tmp_path))
    called = {}

    def fake_impl(job_id, repo_path, spec, initial_spec_path=None):
        called["job_id"] = job_id

    monkeypatch.setattr(activities, "_run_product_analysis_impl", fake_impl)
    activities.run_product_analysis_activity("pa-ok", str(tmp_path), "spec")
    assert called["job_id"] == "pa-ok"


def test_parse_spec_activity_exception_path(
    monkeypatch, tmp_path, patched_job_store, caplog
) -> None:
    """No spec file in repo → spec parser raises FileNotFoundError, which the
    outer except in parse_spec_activity captures and re-raises after marking
    the job FAILED. The failure log carries the trace id bound for this activity."""
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("ps-j", repo_path=str(tmp_path))
    caplog.set_level(logging.ERROR)
    with pytest.raises(Exception):
        activities.parse_spec_activity("ps-j", str(tmp_path), trace_id="parse-spec-trace-id")
    job = js.get_job("ps-j")
    assert job["status"] == js.JOB_STATUS_FAILED

    failure_records = [r for r in caplog.records if "parse_spec_activity failed" in r.message]
    assert failure_records, "expected the failure log to be emitted"
    assert failure_records[-1].trace_id == "parse-spec-trace-id"


def test_parse_spec_activity_non_final_attempt_does_not_mark_failed(
    monkeypatch, tmp_path, patched_job_store
) -> None:
    """No spec file in repo → spec parser raises FileNotFoundError. On a non-final
    Temporal attempt the job is NOT marked FAILED (Temporal will retry) — only the
    final attempt marks it, mirroring the code-v2 activities' guard."""
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("ps-retry", repo_path=str(tmp_path))

    monkeypatch.setattr(activities.activity, "in_activity", lambda: True)
    monkeypatch.setattr(activities.activity, "info", lambda: _fake_activity_info(attempt=1))

    with pytest.raises(Exception):
        activities.parse_spec_activity("ps-retry", str(tmp_path), trace_id="parse-spec-retry")

    job = js.get_job("ps-retry")
    assert job["status"] != js.JOB_STATUS_FAILED


def test_parse_spec_activity_with_sprint_id_matches_shared_helper_output(
    monkeypatch, tmp_path, patched_job_store
) -> None:
    """When sprint_id is set, parse_spec_activity synthesizes spec content via
    shared.sprint_scope.load_requirements_from_sprint (same helper the V1 path
    uses) instead of reading an on-disk spec, and skips the LLM parse + PRA agent
    entirely — no LLM/PRA mocking is needed since neither runs on this path."""
    from datetime import datetime, timezone

    from product_delivery.models import Sprint, SprintWithStories, Story
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.shared.sprint_scope import load_requirements_from_sprint
    from software_engineering_team.temporal import activities

    def _now():
        return datetime.now(tz=timezone.utc)

    story = Story(
        id="story-1",
        epic_id="epic-1",
        title="Login form",
        user_story="As a user, I want to log in",
        status="proposed",
        wsjf_score=None,
        rice_score=None,
        estimate_points=None,
        author="tester",
        created_at=_now(),
        updated_at=_now(),
    )
    sprint = Sprint(
        id="sprint-1",
        product_id="product-1",
        name="Iteration 5",
        capacity_points=13.0,
        starts_at=None,
        ends_at=None,
        status="planned",
        author="tester",
        created_at=_now(),
        updated_at=_now(),
    )
    sprint_view = SprintWithStories(
        sprint=sprint, stories=[story], acceptance_criteria_by_story_id={}
    )

    class _StubStore:
        def get_sprint_with_stories(self, sprint_id: str):
            return sprint_view

    import product_delivery as pd_mod

    monkeypatch.setattr(pd_mod, "get_store", lambda: _StubStore())

    js.create_job("ps-sprint", repo_path=str(tmp_path))
    result = activities.parse_spec_activity(
        "ps-sprint", str(tmp_path), trace_id="t1", sprint_id="sprint-1"
    )

    expected_requirements, expected_spec_content = load_requirements_from_sprint("sprint-1")
    assert result["spec_content"] == expected_spec_content
    assert result["requirements_title"] == expected_requirements.title
    # Sprint path skips PRA: the synthesized spec is used as-is, no PRA iterations.
    assert result["validated_spec"] == expected_spec_content
    assert result["pra_iterations"] == 0

    job = js.get_job("ps-sprint")
    assert job["status"] != js.JOB_STATUS_FAILED


def test_parse_spec_activity_rejects_sprint_id_and_spec_content_override_together(
    tmp_path, patched_job_store
) -> None:
    """sprint_id and spec_content_override are mutually exclusive. Must raise (not
    return normally) — RunTeamWorkflowV2 doesn't inspect SpecParseResult for a
    failure sentinel, so a normal return would let the workflow barrel into
    Phase 2/3 on an empty spec instead of stopping after this activity fails."""
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("ps-both", repo_path=str(tmp_path))
    with pytest.raises(ValueError, match="mutually exclusive"):
        activities.parse_spec_activity(
            "ps-both",
            str(tmp_path),
            spec_content_override="explicit spec",
            sprint_id="sprint-1",
        )
    job = js.get_job("ps-both")
    assert job["status"] == js.JOB_STATUS_FAILED
    assert "mutually exclusive" in (job.get("error") or "")


def test_plan_project_activity_exception_path(monkeypatch, tmp_path, patched_job_store) -> None:
    """Cover the outer except in plan_project_activity.

    Patch ``run_planning_workflow`` to raise — deterministically drives the outer
    ``except`` branch without any network I/O. ``_get_agents`` is stubbed too since
    it runs unconditionally before ``run_planning_workflow`` and would otherwise
    build a real (LLM-backed) agent fleet.
    """
    from unittest.mock import MagicMock

    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("pp-j", repo_path=str(tmp_path))

    # get_client("project_planning") is evaluated as an argument to
    # run_planning_workflow before the patched boom runs; use the dummy provider so
    # it returns a client (rather than raising LLMNotConfiguredError, which would
    # mask the RuntimeError).
    monkeypatch.setenv("LLM_PROVIDER", "dummy")
    monkeypatch.setattr(
        "software_engineering_team.orchestrator._get_agents",
        lambda: {"architecture": MagicMock()},
    )

    def boom(*a, **kw):
        raise RuntimeError("check failed")

    monkeypatch.setattr("planning_team.orchestrator.run_workflow", boom)
    with pytest.raises(RuntimeError):
        activities.plan_project_activity(
            "pp-j",
            str(tmp_path),
            {"spec_content": "spec", "validated_spec": "spec", "plan_dir": str(tmp_path)},
        )
    job = js.get_job("pp-j")
    assert job["status"] == js.JOB_STATUS_FAILED


def test_plan_project_activity_non_final_attempt_does_not_mark_failed(
    monkeypatch, tmp_path, patched_job_store
) -> None:
    """Mirror of test_plan_project_activity_exception_path with a non-final Temporal
    attempt: the job is NOT marked FAILED (Temporal will retry), only re-raised."""
    from unittest.mock import MagicMock

    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("pp-retry", repo_path=str(tmp_path))

    monkeypatch.setenv("LLM_PROVIDER", "dummy")
    monkeypatch.setattr(
        "software_engineering_team.orchestrator._get_agents",
        lambda: {"architecture": MagicMock()},
    )
    monkeypatch.setattr(activities.activity, "in_activity", lambda: True)
    monkeypatch.setattr(activities.activity, "info", lambda: _fake_activity_info(attempt=1))

    def boom(*a, **kw):
        raise RuntimeError("transient planning failure")

    monkeypatch.setattr("planning_team.orchestrator.run_workflow", boom)
    with pytest.raises(RuntimeError):
        activities.plan_project_activity(
            "pp-retry",
            str(tmp_path),
            {"spec_content": "spec", "validated_spec": "spec", "plan_dir": str(tmp_path)},
        )
    job = js.get_job("pp-retry")
    assert job["status"] != js.JOB_STATUS_FAILED


def test_plan_project_activity_wires_lazy_architecture_callback(
    monkeypatch, tmp_path, patched_job_store
) -> None:
    """The activity hands Planning a working architecture callback.

    Regression guard: the callback must resolve ``agents["architecture"]`` lazily (only
    when invoked, not when the activity builds it) and return the agent's overview. This
    exercises the shared ``_make_planning_architecture_fn`` wiring end-to-end through the
    Temporal path, which the mocked-``run_workflow`` tests otherwise never invoke.
    """
    from unittest.mock import MagicMock

    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("pp-wire", repo_path=str(tmp_path))
    monkeypatch.setenv("LLM_PROVIDER", "dummy")

    # A duck-typed architecture agent whose run() yields a scripted overview.
    arch_agent = MagicMock()
    arch_output = MagicMock()
    arch_output.architecture = MagicMock(overview="Wired overview")
    arch_agent.run.return_value = arch_output

    resolved = {"n": 0}

    class _Registry:
        def __getitem__(self, key):
            assert key == "architecture"
            resolved["n"] += 1
            return arch_agent

    monkeypatch.setattr("software_engineering_team.orchestrator._get_agents", lambda: _Registry())

    captured: Dict[str, Any] = {}

    def _fake_run_workflow(*args, **kwargs):
        captured["run_architecture_fn"] = kwargs["run_architecture_fn"]
        # Short-circuit: a failure result makes plan_project_activity return early,
        # before the adapter runs, so this test stays focused on the callback wiring.
        return {"success": False, "failure_reason": "stop here"}

    monkeypatch.setattr("planning_team.orchestrator.run_workflow", _fake_run_workflow)

    mock_record_planning_run = MagicMock()
    monkeypatch.setattr(
        "software_engineering_team.shared.planning_audit.record_se_planning_run",
        mock_record_planning_run,
    )

    activities.plan_project_activity(
        "pp-wire",
        str(tmp_path),
        {"spec_content": "spec", "validated_spec": "spec", "plan_dir": str(tmp_path)},
    )

    # The callback was passed but not yet invoked → the registry must not have been read.
    assert resolved["n"] == 0, "architecture agent must be resolved lazily, not eagerly"

    run_architecture_fn = captured["run_architecture_fn"]
    overview = run_architecture_fn(
        spec_content="# Spec", prd_content=None, repo_path=str(tmp_path), client_context=None
    )

    assert overview == "Wired overview"
    assert resolved["n"] == 1
    # run_workflow short-circuited with success=False above, so the audit write
    # must not fire for this run.
    mock_record_planning_run.assert_not_called()


def test_plan_project_activity_records_planning_run_on_success(
    monkeypatch, tmp_path, patched_job_store
) -> None:
    """On a successful planning run, the activity records a planning_runs audit row.

    Mirrors ``test_plan_project_activity_wires_lazy_architecture_callback``'s setup but
    drives ``run_workflow`` to success instead of short-circuiting on failure — no other
    test in this file reaches ``plan_project_activity``'s success path. ``adapt_planning_result``
    is patched so the test stays focused on the audit-write wiring rather than the adapter.
    """
    from unittest.mock import MagicMock

    from shared.dev_models.models import ProductRequirements
    from software_engineering_team.planning_adapter import PlanningAdapterResult
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("pp-success", repo_path=str(tmp_path))
    monkeypatch.setenv("LLM_PROVIDER", "dummy")

    monkeypatch.setattr(
        "software_engineering_team.orchestrator._get_agents",
        lambda: {"architecture": MagicMock()},
    )

    planning_result = {
        "success": True,
        "summary": "Planning completed; handoff package ready.",
        "handoff_package": {"summary": "Build a widget API."},
        "open_questions": [],
        "resolved_questions": [],
    }
    monkeypatch.setattr("planning_team.orchestrator.run_workflow", lambda *a, **kw: planning_result)

    adapter_result = PlanningAdapterResult(
        requirements=ProductRequirements(
            title="Test",
            description="Desc",
            acceptance_criteria=["Ship it"],
            constraints=[],
        ),
        project_overview={"goals": "Ship", "features_and_functionality_doc": "API"},
        open_questions=[],
        assumptions=[],
    )
    monkeypatch.setattr(
        "software_engineering_team.planning_adapter.adapt_planning_result",
        lambda *a, **kw: adapter_result,
    )

    mock_record_planning_run = MagicMock()
    monkeypatch.setattr(
        "software_engineering_team.shared.planning_audit.record_se_planning_run",
        mock_record_planning_run,
    )

    activities.plan_project_activity(
        "pp-success",
        str(tmp_path),
        {"spec_content": "spec", "validated_spec": "spec", "plan_dir": str(tmp_path)},
    )

    mock_record_planning_run.assert_called_once_with("pp-success", planning_result)


def test_coding_update_callback_forwards_without_heartbeat(monkeypatch) -> None:
    """The callback forwards kwargs to update_job and must NOT heartbeat.

    Liveness is owned solely by the background beater (single-liveness owner), so the
    update callback only persists progress.
    """
    from software_engineering_team.temporal import activities

    captured: Dict[str, Any] = {}
    beats = {"n": 0}
    monkeypatch.setattr(
        activities, "update_job", lambda jid, **kw: captured.update({"jid": jid, **kw})
    )
    monkeypatch.setattr(
        activities.activity, "heartbeat", lambda *a, **k: beats.__setitem__("n", beats["n"] + 1)
    )

    cb = activities._coding_update_callback("job-x")
    cb(status_text="implementing")

    assert captured["jid"] == "job-x"
    assert captured["status_text"] == "implementing"
    assert beats["n"] == 0, "update callback must not emit a heartbeat (single-liveness owner)"


def test_execute_coding_team_activity_exception_path(
    monkeypatch, tmp_path, patched_job_store
) -> None:
    """Bogus adapter_result_dict triggers an exception inside the activity;
    the outer except marks the job FAILED and re-raises."""
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("ec-j", repo_path=str(tmp_path))
    with pytest.raises(Exception):
        activities.execute_coding_team_activity(
            "ec-j",
            str(tmp_path),
            {"adapter_result_dict": {}, "spec_content_for_planning": ""},
        )
    job = js.get_job("ec-j")
    assert job["status"] == js.JOB_STATUS_FAILED


def test_coding_heartbeat_interval_env(monkeypatch) -> None:
    """Interval: valid positive float honored; zero/negative/garbage/unset fall back to 30s."""
    from software_engineering_team.temporal import activities

    monkeypatch.setenv("CODING_TEAM_HEARTBEAT_INTERVAL_S", "12.5")
    assert activities._coding_heartbeat_interval_s() == 12.5
    monkeypatch.setenv("CODING_TEAM_HEARTBEAT_INTERVAL_S", "0")
    assert activities._coding_heartbeat_interval_s() == 30.0
    monkeypatch.setenv("CODING_TEAM_HEARTBEAT_INTERVAL_S", "-5")
    assert activities._coding_heartbeat_interval_s() == 30.0
    monkeypatch.setenv("CODING_TEAM_HEARTBEAT_INTERVAL_S", "garbage")
    assert activities._coding_heartbeat_interval_s() == 30.0
    monkeypatch.delenv("CODING_TEAM_HEARTBEAT_INTERVAL_S", raising=False)
    assert activities._coding_heartbeat_interval_s() == 30.0


def test_execute_coding_team_activity_passes_band_and_default_llm_getter(
    monkeypatch, tmp_path, patched_job_store
) -> None:
    """The Temporal coding activity must mirror the thread path's call contract:
    pass the coding progress band (or the bar collapses to the standalone 0-95
    defaults at the planning handoff) and NOT pass a raw get_llm (the coding
    team's default getter builds strands models with reasoning-stream capture;
    a raw client both looks stalled during long calls and cannot construct
    strands Agent objects)."""
    from software_engineering_team.orchestrator import PROGRESS_BAND_CODING
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("ec-band", repo_path=str(tmp_path))

    captured: Dict[str, Any] = {}

    def fake_orchestrator(job_id, repo_path, plan_input, **kwargs):
        captured.update(kwargs, job_id=job_id)

    import software_engineering_team.coding_team_orchestrator as coding_orch

    monkeypatch.setattr(coding_orch, "run_coding_team_orchestrator", fake_orchestrator)

    from planning_adapter import PlanningAdapterResult

    from shared.dev_models.models import ProductRequirements

    adapter_dict = PlanningAdapterResult(
        requirements=ProductRequirements(
            title="T",
            description="d",
            acceptance_criteria=[],
            constraints=[],
            priority="medium",
            metadata={},
        ),
        project_overview={},
        open_questions=[],
        assumptions=[],
    ).to_dict()
    activities.execute_coding_team_activity(
        "ec-band",
        str(tmp_path),
        {"adapter_result_dict": adapter_dict, "spec_content_for_planning": "s"},
    )

    base, span = PROGRESS_BAND_CODING
    assert captured["job_id"] == "ec-band"
    assert captured["progress_base"] == base
    assert captured["progress_span"] == span
    assert "get_llm" not in captured, (
        "raw get_llm must not be injected: it bypasses the reasoning-stream getter "
        "and hands TechLeadAgent a non-strands client"
    )


def test_execute_coding_team_activity_stays_on_block_pause_strategy(
    monkeypatch, tmp_path, patched_job_store
) -> None:
    """RunTeamWorkflowV2's Phase 3 activity must not opt into pause_strategy="return":
    neither RunTeamWorkflow (V1) nor RunTeamWorkflowV2 defines a submit_answers Temporal
    signal, so a pause under "return" would raise _ActivityPauseSignal with nothing to
    resume it — POST /run-team/{job_id}/answers only ever writes to the job store, it
    never signals a workflow. Regression guard: this pins the "V2 HITL == V1 HITL"
    equivalence this codebase currently relies on for job-store-poll-based resume."""
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("ec-pause-strategy", repo_path=str(tmp_path))

    captured: Dict[str, Any] = {}

    def fake_orchestrator(job_id, repo_path, plan_input, **kwargs):
        captured.update(kwargs)

    import software_engineering_team.coding_team_orchestrator as coding_orch

    monkeypatch.setattr(coding_orch, "run_coding_team_orchestrator", fake_orchestrator)

    from planning_adapter import PlanningAdapterResult

    from shared.dev_models.models import ProductRequirements

    adapter_dict = PlanningAdapterResult(
        requirements=ProductRequirements(
            title="T",
            description="d",
            acceptance_criteria=[],
            constraints=[],
            priority="medium",
            metadata={},
        ),
        project_overview={},
        open_questions=[],
        assumptions=[],
    ).to_dict()
    activities.execute_coding_team_activity(
        "ec-pause-strategy",
        str(tmp_path),
        {"adapter_result_dict": adapter_dict, "spec_content_for_planning": "s"},
    )

    assert captured.get("pause_strategy", "block") == "block", (
        'execute_coding_team_activity must not pass pause_strategy="return" until '
        "RunTeamWorkflowV2 defines a submit_answers signal to resume it"
    )


def test_pra_and_planning_phase_updaters_rescale_progress_to_bands(monkeypatch) -> None:
    """``_make_phase_job_updater`` rescales a sub-agent's raw 0-100 progress onto
    its phase's progress band, for both the PRA and Planning phase configs —
    without this, sub-agent progress would sprint to 100 during a phase and
    collapse at the next phase handoff.

    This test calls the factory directly and only verifies its band math; it
    does not exercise ``_parse_spec_activity_body``/``_plan_project_activity_body``
    (the Temporal activity bodies that import and bind this same factory), so it
    does not verify that those activities are actually wired to it.
    """
    import software_engineering_team.orchestrator as se_orch

    written: list = []
    monkeypatch.setattr(se_orch, "update_job", lambda job_id, **kw: written.append(kw))

    # The factories are what the activities now bind; assert their band behavior
    # end-to-end through the same entry points the activities import.
    pra = se_orch._make_phase_job_updater(
        "j-t",
        subprocess_key="analysis_subprocess",
        completed_key="analysis_completed_phases",
        phase_order=se_orch.PRA_PHASE_ORDER,
        progress_band=se_orch.PROGRESS_BAND_PRODUCT_ANALYSIS,
        phase="product_analysis",
    )
    pra(progress=100)
    assert (
        written[-1]["progress"]
        == se_orch.PROGRESS_BAND_PRODUCT_ANALYSIS[0] + (se_orch.PROGRESS_BAND_PRODUCT_ANALYSIS[1])
    )

    planning = se_orch._make_phase_job_updater(
        "j-t",
        subprocess_key="planning_subprocess",
        completed_key="planning_completed_phases",
        phase_order=se_orch.PLANNING_PHASE_ORDER,
        progress_band=se_orch.PROGRESS_BAND_PLANNING,
    )
    planning(progress=100)
    base, span = se_orch.PROGRESS_BAND_PLANNING
    assert written[-1]["progress"] == base + span


def test_adapter_result_round_trips_through_dict() -> None:
    """The Temporal planning→coding handoff serializes the adapter dataclass with
    to_dict/from_dict. The old hasattr(model_dump) probe silently produced {} for
    the dataclass, so the coding activity could never reconstruct it — this pins
    a lossless round trip including the nested Pydantic models."""
    import json

    from planning_adapter import PlanningAdapterResult

    from shared.dev_models.models import ProductRequirements

    original = PlanningAdapterResult(
        requirements=ProductRequirements(
            title="Build it",
            description="desc",
            acceptance_criteria=["works"],
            constraints=["python"],
            priority="high",
            metadata={"k": "v"},
        ),
        project_overview={"goals": "g"},
        open_questions=["q1"],
        assumptions=["a1"],
        final_spec_content="spec",
        architecture_overview="arch",
        shared_planning_doc_path="/plan/doc.md",
        resolved_questions=[{"id": "q1", "answer": "yes"}],
    )

    payload = original.to_dict()
    json.dumps(payload)  # must be JSON-safe for the Temporal payload converter

    rebuilt = PlanningAdapterResult.from_dict(payload)
    assert rebuilt.requirements == original.requirements
    assert rebuilt.project_overview == original.project_overview
    assert rebuilt.open_questions == original.open_questions
    assert rebuilt.assumptions == original.assumptions
    assert rebuilt.hierarchy is None
    assert rebuilt.final_spec_content == "spec"
    assert rebuilt.architecture_overview == "arch"
    assert rebuilt.shared_planning_doc_path == "/plan/doc.md"
    assert rebuilt.resolved_questions == original.resolved_questions


def test_parse_spec_activity_binds_the_passed_trace_id(
    monkeypatch, tmp_path, patched_job_store
) -> None:
    """Each phase activity runs as its own process/thread invocation (no shared contextvar
    context with the workflow or the other phase activities), so ``trace_id`` must be passed
    explicitly and re-bound inside the activity — this pins that ``parse_spec_activity`` does so."""
    from shared.observability import current_trace_id
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("ps-trace", repo_path=str(tmp_path))
    monkeypatch.setenv("LLM_PROVIDER", "dummy")
    (tmp_path / "initial_spec.md").write_text("# Test\n\nSpec.", encoding="utf-8")

    seen = {}

    def fake_parse_spec_with_llm(*a, **kw):
        seen["trace_id"] = current_trace_id()
        raise RuntimeError("stop after capturing trace_id")

    monkeypatch.setattr(
        "software_engineering_team.spec_parser.parse_spec_with_llm", fake_parse_spec_with_llm
    )
    with pytest.raises(RuntimeError, match="stop after capturing trace_id"):
        activities.parse_spec_activity("ps-trace", str(tmp_path), trace_id="fixed-trace-1")
    assert seen["trace_id"] == "fixed-trace-1"
    assert current_trace_id() == ""  # unbound again once the activity returns/raises


def test_plan_project_activity_binds_the_passed_trace_id(
    monkeypatch, tmp_path, patched_job_store
) -> None:
    """See ``test_parse_spec_activity_binds_the_passed_trace_id``; same contract for Phase 2."""
    from unittest.mock import MagicMock

    from shared.observability import current_trace_id
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("pp-trace", repo_path=str(tmp_path))
    monkeypatch.setenv("LLM_PROVIDER", "dummy")
    monkeypatch.setattr(
        "software_engineering_team.orchestrator._get_agents",
        lambda: {"architecture": MagicMock()},
    )

    seen = {}

    def fake_run_planning_workflow(*a, **kw):
        seen["trace_id"] = current_trace_id()
        raise RuntimeError("stop after capturing trace_id")

    monkeypatch.setattr("planning_team.orchestrator.run_workflow", fake_run_planning_workflow)
    with pytest.raises(RuntimeError, match="stop after capturing trace_id"):
        activities.plan_project_activity(
            "pp-trace",
            str(tmp_path),
            {"spec_content": "spec", "validated_spec": "spec", "plan_dir": str(tmp_path)},
            trace_id="fixed-trace-2",
        )
    assert seen["trace_id"] == "fixed-trace-2"
    assert current_trace_id() == ""


def test_execute_coding_team_activity_binds_the_passed_trace_id(
    monkeypatch, tmp_path, patched_job_store
) -> None:
    """See ``test_parse_spec_activity_binds_the_passed_trace_id``; same contract for Phase 3 —
    including the ``parallel_map`` fan-out inside ``run_coding_team_orchestrator``, which inherits
    the bound id via ``contextvars.copy_context()`` once it is bound here."""
    from planning_adapter import PlanningAdapterResult

    from shared.dev_models.models import ProductRequirements
    from shared.observability import current_trace_id
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("ec-trace", repo_path=str(tmp_path))

    seen = {}

    def fake_run_coding_team_orchestrator(job_id, repo_path, plan_input, **kwargs):
        seen["trace_id"] = current_trace_id()

    monkeypatch.setattr(
        "software_engineering_team.coding_team_orchestrator.run_coding_team_orchestrator",
        fake_run_coding_team_orchestrator,
    )

    adapter_dict = PlanningAdapterResult(
        requirements=ProductRequirements(
            title="T", description="d", acceptance_criteria=[], constraints=[]
        ),
        project_overview={},
        open_questions=[],
        assumptions=[],
    ).to_dict()
    activities.execute_coding_team_activity(
        "ec-trace",
        str(tmp_path),
        {"adapter_result_dict": adapter_dict, "spec_content_for_planning": "s"},
        trace_id="fixed-trace-3",
    )
    assert seen["trace_id"] == "fixed-trace-3"
    assert current_trace_id() == ""


def test_phase_activities_generate_a_trace_id_when_none_supplied(
    monkeypatch, tmp_path, patched_job_store
) -> None:
    """A blank ``trace_id`` (Temporal's default when a caller omits it) still binds a non-empty,
    generated id rather than leaving the phase's logs uncorrelated."""
    from shared.observability import current_trace_id
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("ps-notrace", repo_path=str(tmp_path))
    monkeypatch.setenv("LLM_PROVIDER", "dummy")
    (tmp_path / "initial_spec.md").write_text("# Test\n\nSpec.", encoding="utf-8")

    seen = {}

    def fake_parse_spec_with_llm(*a, **kw):
        seen["trace_id"] = current_trace_id()
        raise RuntimeError("stop after capturing trace_id")

    monkeypatch.setattr(
        "software_engineering_team.spec_parser.parse_spec_with_llm", fake_parse_spec_with_llm
    )
    with pytest.raises(RuntimeError):
        activities.parse_spec_activity("ps-notrace", str(tmp_path))
    assert seen["trace_id"]


def test_plan_project_activity_pauses_on_planning_clarification_question(
    monkeypatch, tmp_path, patched_job_store
) -> None:
    """A fresh clarification question durably pauses instead of blocking or auto-answering.

    Regression guard for the Temporal-mode HITL gap: when Planning's
    ``answer_callback`` is invoked with no ``submitted_answers`` yet, the primitive from
    ``planning_team.temporal.answer_signal`` raises ``PlanningAnswerPauseSignal`` instead of
    returning a default. The activity must catch it, persist the question via
    ``add_pending_questions`` (the same call thread-mode's own
    ``orchestrator._build_planning_answer_callback`` makes), and return a discriminated
    ``{"outcome": "paused", ...}`` dict rather than a ``PlanResult`` or a raised exception.
    """
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("pp-pause", repo_path=str(tmp_path), job_type="run_team")
    monkeypatch.setenv("LLM_PROVIDER", "dummy")
    monkeypatch.setattr(
        "software_engineering_team.orchestrator._get_agents",
        lambda: {"architecture": None},
    )

    def _fake_run_workflow(*args, **kwargs):
        answer_callback = kwargs["answer_callback"]
        assert kwargs["auto_answer_questions"] is False
        # Never returns: the callback raises PlanningAnswerPauseSignal for a fresh pause.
        return answer_callback(
            [
                {
                    "id": "q1",
                    "question_text": "Which auth provider?",
                    "options": [{"id": "okta", "label": "Okta"}],
                }
            ]
        )

    monkeypatch.setattr("planning_team.orchestrator.run_workflow", _fake_run_workflow)

    result = activities.plan_project_activity(
        "pp-pause",
        str(tmp_path),
        {"spec_content": "spec", "validated_spec": "spec", "plan_dir": str(tmp_path)},
    )

    assert result["outcome"] == "paused"
    assert isinstance(result["resume_token"], str) and result["resume_token"]
    assert result["pending_questions"][0]["question_text"] == "Which auth provider?"
    assert result["pending_questions"][0]["id"] == "q1"
    assert result["pending_questions"][0]["options"] == [{"id": "okta", "label": "Okta"}]

    job = js.get_job("pp-pause")
    assert job["waiting_for_answers"] is True
    assert job["pending_questions"][0]["question_text"] == "Which auth provider?"
    # Never marked failed by the generic exception handler — a pause is not a failure.
    assert job["status"] != js.JOB_STATUS_FAILED
    # Persisted onto the job record so POST /run-team/{job_id}/answers has something to
    # key its Temporal-native-vs-thread-mode decision on (see api/routes/hitl.py).
    assert job["resume_token"] == result["resume_token"]


def test_plan_project_activity_resumes_with_submitted_answers(
    monkeypatch, tmp_path, patched_job_store
) -> None:
    """Re-invoking with ``resume_token``/``submitted_answers`` resolves the same question
    instead of pausing again, and Planning proceeds to completion."""
    from unittest.mock import MagicMock

    from shared.dev_models.models import ProductRequirements
    from software_engineering_team.planning_adapter import PlanningAdapterResult
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("pp-resume", repo_path=str(tmp_path), job_type="run_team")
    # Simulate the pause envelope a prior invocation already persisted -- the resume path
    # must clear it atomically once it consumes this exact token, not leave it stale.
    js.update_job(
        "pp-resume",
        waiting_for_answers=True,
        resume_token="pp-resume:abc123",
        pending_questions=[{"id": "q1", "question_text": "Which auth provider?"}],
    )
    monkeypatch.setenv("LLM_PROVIDER", "dummy")
    monkeypatch.setattr(
        "software_engineering_team.orchestrator._get_agents",
        lambda: {"architecture": MagicMock()},
    )

    captured: Dict[str, Any] = {}

    def _fake_run_workflow(*args, **kwargs):
        answer_callback = kwargs["answer_callback"]
        captured["answers"] = answer_callback(
            [{"id": "q1", "question_text": "Which auth provider?"}]
        )
        return {
            "success": True,
            "summary": "done",
            "handoff_package": {"summary": "Build a widget API."},
            "open_questions": [],
            "resolved_questions": [],
        }

    monkeypatch.setattr("planning_team.orchestrator.run_workflow", _fake_run_workflow)

    adapter_result = PlanningAdapterResult(
        requirements=ProductRequirements(
            title="Test", description="Desc", acceptance_criteria=["Ship it"], constraints=[]
        ),
        project_overview={"goals": "Ship", "features_and_functionality_doc": "API"},
        open_questions=[],
        assumptions=[],
    )
    monkeypatch.setattr(
        "software_engineering_team.planning_adapter.adapt_planning_result",
        lambda *a, **kw: adapter_result,
    )

    result = activities.plan_project_activity(
        "pp-resume",
        str(tmp_path),
        {"spec_content": "spec", "validated_spec": "spec", "plan_dir": str(tmp_path)},
        resume_token="pp-resume:abc123",
        submitted_answers=[{"question_id": "q1", "selected_option_id": "okta"}],
    )

    assert captured["answers"] == [{"question_id": "q1", "selected_option_id": "okta"}]
    assert "outcome" not in result or result.get("outcome") != "paused"
    assert result["requirements_title"] == "Test"

    job = js.get_job("pp-resume")
    assert job["waiting_for_answers"] is False
    assert job["pending_questions"] == []
    assert job["resume_token"] is None


def test_plan_project_activity_final_round_resolves_a_drifted_question_instead_of_pausing(
    monkeypatch, tmp_path, patched_job_store
) -> None:
    """``allow_repause=False`` is how the workflow's bounded pause loop terminates.

    Planning's question ids come straight from LLM output, so a from-scratch
    replay can present an id nobody has been shown even though the user has
    already answered the same question. With the pause budget spent the
    activity must return a PlanResult rather than a fourth-and-forever
    ``{"outcome": "paused"}``.
    """
    from unittest.mock import MagicMock

    from shared.dev_models.models import ProductRequirements
    from software_engineering_team.planning_adapter import PlanningAdapterResult
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("pp-final", repo_path=str(tmp_path), job_type="run_team")
    js.update_job(
        "pp-final",
        waiting_for_answers=True,
        resume_token="pp-final:abc123",
        pending_questions=[{"id": "q1", "question_text": "Which auth provider?"}],
    )
    monkeypatch.setenv("LLM_PROVIDER", "dummy")
    monkeypatch.setattr(
        "software_engineering_team.orchestrator._get_agents",
        lambda: {"architecture": MagicMock()},
    )

    captured: Dict[str, Any] = {}

    def _fake_run_workflow(*args, **kwargs):
        # The replay minted a different id for the same question.
        captured["answers"] = kwargs["answer_callback"](
            [{"id": "q1-regenerated", "question_text": "Which auth provider?"}]
        )
        return {
            "success": True,
            "summary": "done",
            "handoff_package": {"summary": "Build a widget API."},
            "open_questions": [],
            "resolved_questions": [],
        }

    monkeypatch.setattr("planning_team.orchestrator.run_workflow", _fake_run_workflow)
    monkeypatch.setattr(
        "software_engineering_team.planning_adapter.adapt_planning_result",
        lambda *a, **kw: PlanningAdapterResult(
            requirements=ProductRequirements(
                title="Test", description="Desc", acceptance_criteria=["Ship it"], constraints=[]
            ),
            project_overview={"goals": "Ship", "features_and_functionality_doc": "API"},
            open_questions=[],
            assumptions=[],
        ),
    )

    result = activities.plan_project_activity(
        "pp-final",
        str(tmp_path),
        {"spec_content": "spec", "validated_spec": "spec", "plan_dir": str(tmp_path)},
        resume_token="pp-final:abc123",
        submitted_answers=[{"question_id": "q1", "selected_option_id": "okta"}],
        allow_repause=False,
    )

    # The drifted id matches no submitted answer, so the final round defaults it
    # rather than submitting a short set the answers route would reject -- the
    # compromise the warning in build_temporal_planning_answer_callback names.
    assert captured["answers"] == [
        {"question_id": "q1-regenerated", "selected_option_id": None, "other_text": None}
    ]
    assert result.get("outcome") != "paused"
    assert result["requirements_title"] == "Test"

    # The job record too, matching the sibling pause test's pattern: a final round
    # that returned a PlanResult but left the pause envelope standing, or marked
    # the job failed through the generic handler, would pass the assertions above.
    # NB the answered-token marker is written by the answers ROUTE, not by this
    # activity, so it is not assertable here; what the activity guarantees is that
    # it consumed the envelope it re-entered on.
    job = js.get_job("pp-final")
    assert job["status"] != js.JOB_STATUS_FAILED
    assert job["waiting_for_answers"] is False
    assert job["pending_questions"] == []
    assert job["resume_token"] is None

    # The whole justification for defaulting rather than hanging is that the
    # choice is announced. A worker log line is not an announcement anything
    # downstream can read, so the activity records it on the job -- and
    # build_job_status_response surfaces it from there.
    assert job["defaulted_questions"] == [
        {
            "question_id": "q1-regenerated",
            "question_text": "Which auth provider?",
            "selected_option_id": None,
            "selected_option_label": None,
        }
    ]


def test_defaulted_questions_accumulate_across_pra_rounds(tmp_path, patched_job_store) -> None:
    """The hook fires once per PRA clarification ROUND, not once per execution.

    ``_on_poll`` re-invokes the same callback on every poll while PRA reports
    waiting_for_answers, and PRA raises several unrelated rounds with fresh ids.
    A plain overwrite would leave only the last round in the audit record,
    silently discarding the evidence that earlier rounds were fabricated too.
    """
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal.activities import _record_defaulted_questions

    js.create_job("pp-multi", repo_path=str(tmp_path), job_type="run_team")
    record = _record_defaulted_questions("pp-multi")

    record([{"question_id": "q1", "question_text": "Which auth?", "selected_option_id": "a"}])
    record([{"question_id": "q2", "question_text": "Which store?", "selected_option_id": "b"}])

    assert [r["question_id"] for r in js.get_job("pp-multi")["defaulted_questions"]] == [
        "q1",
        "q2",
    ]


def test_defaulted_questions_keep_rounds_that_reuse_a_question_id(
    tmp_path, patched_job_store
) -> None:
    """Identity is (question_id, question_text), never the id alone.

    PRA's parser falls back to a positional ``q{index}`` id, so two unrelated
    rounds can both call their first question ``q0``. Keying on the id alone would
    drop the second as a duplicate and lose a real fabricated answer.
    """
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal.activities import _record_defaulted_questions

    js.create_job("pp-collide", repo_path=str(tmp_path), job_type="run_team")
    record = _record_defaulted_questions("pp-collide")

    record([{"question_id": "q0", "question_text": "Which auth?", "selected_option_id": "a"}])
    record([{"question_id": "q0", "question_text": "Which region?", "selected_option_id": "b"}])

    stored = js.get_job("pp-collide")["defaulted_questions"]
    assert [r["question_text"] for r in stored] == ["Which auth?", "Which region?"]


def test_defaulted_questions_do_not_double_on_a_repeated_poll(tmp_path, patched_job_store) -> None:
    """A poll-repeat of the same question is one entry, not one row per poll.

    ``_on_poll`` re-presents a still-unanswered batch on every poll and each is
    defaulted again. ``_default_answer`` is deterministic for a given question, so
    a genuine repeat produces an IDENTICAL record -- which is what the key
    collapses. Without this, one question inflates into a row per poll.
    """
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal.activities import _record_defaulted_questions

    js.create_job("pp-repeat", repo_path=str(tmp_path), job_type="run_team")
    record = _record_defaulted_questions("pp-repeat")

    batch = [
        {
            "question_id": "q1",
            "question_text": "Same",
            "selected_option_id": "a",
            "selected_option_label": "A",
        }
    ]
    record(batch)
    record(batch)

    assert js.get_job("pp-repeat")["defaulted_questions"] == batch


def test_rounds_that_match_on_id_and_text_but_differ_in_selection_both_survive(
    tmp_path, patched_job_store
) -> None:
    """Identity is the whole record, not the ``(id, question_text)`` pair.

    PRA's parser defaults both ``id`` and ``question_text`` identically across
    separate rounds, so two unrelated rounds can coincide on that pair while
    offering different options -- and collapsing them would discard a real audit
    event. SPEC-024 risk 3 makes this correction explicitly, superseding an earlier
    draft that specified the pair.
    """
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal.activities import _record_defaulted_questions

    js.create_job("pp-differ", repo_path=str(tmp_path), job_type="run_team")
    record = _record_defaulted_questions("pp-differ")

    record(
        [
            {
                "question_id": "q0",
                "question_text": "Pick one",
                "selected_option_id": "a",
                "selected_option_label": "Postgres",
            }
        ]
    )
    record(
        [
            {
                "question_id": "q0",
                "question_text": "Pick one",
                "selected_option_id": "b",
                "selected_option_label": "Redis",
            }
        ]
    )

    stored = js.get_job("pp-differ")["defaulted_questions"]
    assert [r["selected_option_label"] for r in stored] == ["Postgres", "Redis"]


def test_a_retry_rebuilds_defaulted_questions_rather_than_doubling_them(
    tmp_path, patched_job_store
) -> None:
    """A Temporal retry runs a fresh accumulator and rewrites the whole field.

    Writing the accumulated list (rather than appending server-side) is what keeps
    the retry idempotent -- the deterministic replay recomputes the same records
    and overwrites, instead of stacking a second copy onto the first attempt's.
    """
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal.activities import _record_defaulted_questions

    js.create_job("pp-retry", repo_path=str(tmp_path), job_type="run_team")
    batch = [{"question_id": "q1", "question_text": "T", "selected_option_id": "a"}]

    _record_defaulted_questions("pp-retry")(batch)
    _record_defaulted_questions("pp-retry")(batch)  # the retry

    assert js.get_job("pp-retry")["defaulted_questions"] == batch


def test_a_terminal_attempt_clears_defaults_it_does_not_reproduce(
    monkeypatch, tmp_path, patched_job_store
) -> None:
    """A retried terminal attempt must not inherit the previous attempt's records.

    The hook only ever writes. This activity is retryable and the pause envelope is
    consumed on the first attempt, so a retry replays Planning from scratch; if that
    replay matches every question the hook never fires. Without a clear, the job
    would report machine-chosen answers for a plan that shipped fully
    human-answered -- over-reporting, but still a reason to distrust the field.
    """
    from unittest.mock import MagicMock

    from shared.dev_models.models import ProductRequirements
    from software_engineering_team.planning_adapter import PlanningAdapterResult
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("pp-stale", repo_path=str(tmp_path), job_type="run_team")
    # The failed attempt's leftovers.
    js.update_job(
        "pp-stale",
        defaulted_questions=[
            {"question_id": "old", "question_text": "Stale", "selected_option_id": "x"}
        ],
    )
    monkeypatch.setenv("LLM_PROVIDER", "dummy")
    monkeypatch.setattr(
        "software_engineering_team.orchestrator._get_agents",
        lambda: {"architecture": MagicMock()},
    )

    def _fake_run_workflow(*args, **kwargs):
        # This replay matches everything, so the callback defaults nothing.
        kwargs["answer_callback"]([{"id": "q1", "question_text": "Which auth provider?"}])
        return {
            "success": True,
            "summary": "done",
            "handoff_package": {"summary": "Build a widget API."},
            "open_questions": [],
            "resolved_questions": [],
        }

    monkeypatch.setattr("planning_team.orchestrator.run_workflow", _fake_run_workflow)
    monkeypatch.setattr(
        "software_engineering_team.planning_adapter.adapt_planning_result",
        lambda *a, **kw: PlanningAdapterResult(
            requirements=ProductRequirements(
                title="Test", description="D", acceptance_criteria=["Ship"], constraints=[]
            ),
            project_overview={"goals": "Ship", "features_and_functionality_doc": "API"},
            open_questions=[],
            assumptions=[],
        ),
    )

    result = activities.plan_project_activity(
        "pp-stale",
        str(tmp_path),
        {"spec_content": "spec", "validated_spec": "spec", "plan_dir": str(tmp_path)},
        submitted_answers=[{"question_id": "q1", "selected_option_id": "okta"}],
        allow_repause=False,
    )

    # Assert the activity actually succeeded before trusting the empty field, the
    # same guard the sibling drifted-question test carries. Without it, a
    # regression that cleared the field and then failed the job through the
    # generic error handler -- or returned a paused outcome -- would pass this
    # test green while the behaviour it protects was broken.
    assert result.get("outcome") != "paused"
    assert result["requirements_title"] == "Test"

    job = js.get_job("pp-stale")
    assert job["status"] != js.JOB_STATUS_FAILED
    assert job["defaulted_questions"] == []


def test_a_failed_audit_write_raises_a_passthrough_exception(tmp_path, patched_job_store) -> None:
    """The hook must fail the round, and only one exception type actually does.

    ``poll_until_terminal`` folds an ordinary ``on_poll`` exception into a failed
    status and ``DocumentProductionAgent.run`` logs that and carries on, so a plain
    raise would ship fabricated answers with no record of them. Both boundaries pass
    ``PlanningDefaultsNotRecorded`` through instead.
    """
    from unittest.mock import patch

    from planning_team.exceptions import PlanningDefaultsNotRecorded
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal.activities import _record_defaulted_questions

    js.create_job("pp-writefail", repo_path=str(tmp_path), job_type="run_team")
    record = _record_defaulted_questions("pp-writefail")

    with patch(
        "software_engineering_team.temporal.activities.update_job",
        side_effect=RuntimeError("job store down"),
    ):
        with pytest.raises(PlanningDefaultsNotRecorded) as exc:
            record([{"question_id": "q1", "question_text": "T", "selected_option_id": "a"}])

    assert exc.value.job_id == "pp-writefail"
    assert exc.value.record_count == 1
    # The original failure is preserved for whoever debugs the retry.
    assert isinstance(exc.value.__cause__, RuntimeError)


def test_record_defaulted_questions_requires_a_job_id() -> None:
    """A blank job_id would silently write nowhere, leaving the terminal round's
    fabrication unrecorded -- the one outcome this hook exists to rule out.
    """
    from software_engineering_team.temporal.activities import _record_defaulted_questions

    with pytest.raises(AssertionError, match="job_id"):
        _record_defaulted_questions("")


def test_plan_project_status_omits_defaults_when_a_human_answered_everything(
    tmp_path, patched_job_store
) -> None:
    """An empty ``defaulted_questions`` is a claim, not an absence: every answer
    behind this plan came from a person. It must be an empty list rather than a
    missing key or None, so a client can read it without special-casing the
    common path.
    """
    from software_engineering_team.api.state import build_job_status_response
    from software_engineering_team.shared import job_store as js

    js.create_job("pp-clean", repo_path=str(tmp_path), job_type="run_team")

    assert build_job_status_response("pp-clean", js.get_job("pp-clean")).defaulted_questions == []


def test_plan_project_status_surfaces_defaulted_questions(tmp_path, patched_job_store) -> None:
    """The persisted record has to reach the client. ``build_job_status_response``
    assembles an explicit payload dict, so a field absent from it is dropped
    silently -- the audit trail would stop at the job record and the UI would show
    a plan that looks fully human-answered.
    """
    from software_engineering_team.api.state import build_job_status_response
    from software_engineering_team.shared import job_store as js

    js.create_job("pp-defaulted", repo_path=str(tmp_path), job_type="run_team")
    js.update_job(
        "pp-defaulted",
        defaulted_questions=[{"question_id": "q9", "selected_option_id": "opt-b"}],
    )

    response = build_job_status_response("pp-defaulted", js.get_job("pp-defaulted"))

    # A typed field, so the response carries the full declared shape rather than
    # echoing whatever the job record happened to store.
    assert [dq.model_dump() for dq in response.defaulted_questions] == [
        {
            "question_id": "q9",
            "question_text": None,
            "selected_option_id": "opt-b",
            "selected_option_label": None,
        }
    ]


def test_plan_project_status_degrades_a_malformed_defaulted_questions_value(
    tmp_path, patched_job_store
) -> None:
    """A status endpoint that 500s on a corrupt record tells the user nothing.

    The two cases degrade differently, and deliberately so: a non-list carries no
    salvageable entry, so it becomes the empty list a job that defaulted nothing
    reports; non-dict entries inside a list are dropped while the valid dicts are
    kept, because discarding a real record alongside the junk would under-report
    fabricated answers -- the failure direction this feature exists to close.
    """
    from software_engineering_team.api.state import build_job_status_response
    from software_engineering_team.shared import job_store as js

    js.create_job("pp-garbled", repo_path=str(tmp_path), job_type="run_team")
    js.update_job("pp-garbled", defaulted_questions="not-a-list")
    assert (
        build_job_status_response("pp-garbled", js.get_job("pp-garbled")).defaulted_questions == []
    )

    js.update_job("pp-garbled", defaulted_questions=[{"question_id": "q1"}, "junk", 7])
    kept = build_job_status_response("pp-garbled", js.get_job("pp-garbled")).defaulted_questions
    assert [dq.question_id for dq in kept] == ["q1"]
    # The surviving entry is filled out to the declared shape, not passed through:
    # a stored dict missing keys must not yield a row missing fields.
    assert kept[0].question_text is None
    assert kept[0].selected_option_label is None


def test_plan_project_activity_retry_reemits_persisted_pause_without_rerunning(
    monkeypatch, tmp_path, patched_job_store
) -> None:
    """A Temporal activity retry of the ORIGINAL (fresh) invocation -- no resume_token, no
    submitted_answers, exactly the args the workflow's first execute_activity call used --
    must detect the pause a prior attempt already persisted and re-emit that exact
    resume_token/pending_questions, never re-run Planning and mint a second, different
    token (which would strand whichever token the user was already shown)."""
    from software_engineering_team.shared import job_store as js
    from software_engineering_team.temporal import activities

    js.create_job("pp-retry", repo_path=str(tmp_path), job_type="run_team")
    js.update_job(
        "pp-retry",
        waiting_for_answers=True,
        resume_token="pp-retry:orig-token",
        pending_questions=[{"id": "q1", "question_text": "Which auth provider?"}],
    )

    def _must_not_run(*a, **kw):  # pragma: no cover
        raise AssertionError("a retry re-entry must never re-run Planning")

    monkeypatch.setattr("planning_team.orchestrator.run_workflow", _must_not_run)

    result = activities.plan_project_activity(
        "pp-retry",
        str(tmp_path),
        {"spec_content": "spec", "validated_spec": "spec", "plan_dir": str(tmp_path)},
    )

    assert result == {
        "outcome": "paused",
        "resume_token": "pp-retry:orig-token",
        "pending_questions": [{"id": "q1", "question_text": "Which auth provider?"}],
    }
    # The persisted pause is untouched -- re-emitting it is not the same as re-pausing it.
    job = js.get_job("pp-retry")
    assert job["resume_token"] == "pp-retry:orig-token"
    assert job["waiting_for_answers"] is True
