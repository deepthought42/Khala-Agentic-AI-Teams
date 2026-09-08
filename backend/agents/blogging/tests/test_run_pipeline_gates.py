"""Drive run_pipeline with gates enabled to cover the rewrite loop branches.

Tests:
* All gates PASS → status=PASS
* Gates FAIL on iter 1, PASS on iter 2 → status=PASS
* Gates never pass → status=NEEDS_HUMAN_REVIEW
* publishing_pack.json's title_options sources from ctx.selected_title, with the
  plan-candidates fallback when selection was skipped
* The gates rewrite loop's ReviseWriterInput carries ctx.selected_title

Uses the shared ContentPlan factory from ``_content_plan_test_utils``.
"""

from __future__ import annotations

from pathlib import Path

from .conftest import make_stub_editor_class, make_stub_writer_class


def _make_plan():
    from ._content_plan_test_utils import make_minimal_planning_phase_result

    return make_minimal_planning_phase_result()


def _stub_compliance(status: str = "PASS"):
    from agents.blogging.blog_compliance_agent.models import ComplianceReport

    class _Stub:
        def __init__(self, *a, **kw):
            pass

        def run(self, *a, **kw):
            return ComplianceReport(status=status, violations=[], required_fixes=[], notes="ok")

    return _Stub


def _stub_factcheck(claims_status: str = "PASS", risk_status: str = "PASS"):
    from agents.blogging.blog_fact_check_agent.models import FactCheckReport

    class _Stub:
        def __init__(self, *a, **kw):
            pass

        def run(self, *a, **kw):
            return FactCheckReport(
                claims_status=claims_status,
                risk_status=risk_status,
                risk_flags=[] if risk_status == "PASS" else ["claim X"],
                required_disclaimers=[],
                unverified_claims=[],
                claims=[],
            )

    return _Stub


class _ValidatorStub:
    def __init__(self, status: str = "PASS"):
        self.status = status
        self.checks = []

    def model_dump(self):
        return {"status": self.status, "checks": []}


def _common_v2_setup(monkeypatch, validator_status: str = "PASS"):
    """Apply the standard set of monkeypatches to v2 for gate tests."""
    import agents.blogging.agent_implementations.blog_writing_process_v2 as v2

    monkeypatch.setattr(v2, "run_planning", lambda *a, **kw: _make_plan())
    monkeypatch.setattr(v2, "load_style_file", lambda *a, **kw: "ok")
    monkeypatch.setattr(v2, "load_brand_spec_prompt", lambda *a, **kw: "brand")
    monkeypatch.setattr(v2, "BlogWriterAgent", make_stub_writer_class())
    monkeypatch.setattr(v2, "BlogCopyEditorAgent", make_stub_editor_class())
    monkeypatch.setattr(
        v2,
        "run_validators_from_work_dir",
        lambda wd, **kw: _ValidatorStub(status=validator_status),
    )
    return v2


def test_run_pipeline_with_gates_all_pass(monkeypatch, tmp_path: Path) -> None:
    """All gates pass on iteration 1 → status=PASS."""
    v2 = _common_v2_setup(monkeypatch, validator_status="PASS")
    monkeypatch.setattr(v2, "BlogComplianceAgent", _stub_compliance("PASS"))
    monkeypatch.setattr(v2, "BlogFactCheckAgent", _stub_factcheck("PASS", "PASS"))

    from agents.blogging.blog_research_agent.models import ResearchBriefInput

    brief = ResearchBriefInput(brief="hi", max_results=5)
    _, _, status = v2.run_pipeline(
        brief,
        work_dir=tmp_path / "wd",
        run_gates=True,
        max_rewrite_iterations=2,
        draft_editor_iterations=1,
    )
    assert status == "PASS"


def test_run_pipeline_with_gates_exhausts_iterations(monkeypatch, tmp_path: Path) -> None:
    """Gates never pass → status=NEEDS_HUMAN_REVIEW after max_rewrite_iterations."""
    v2 = _common_v2_setup(monkeypatch, validator_status="FAIL")
    monkeypatch.setattr(v2, "BlogComplianceAgent", _stub_compliance("FAIL"))
    monkeypatch.setattr(v2, "BlogFactCheckAgent", _stub_factcheck("FAIL", "FAIL"))

    from agents.blogging.blog_research_agent.models import ResearchBriefInput

    brief = ResearchBriefInput(brief="hi", max_results=5)
    _, _, status = v2.run_pipeline(
        brief,
        work_dir=tmp_path / "wd",
        run_gates=True,
        max_rewrite_iterations=1,
        draft_editor_iterations=1,
    )
    assert status == "NEEDS_HUMAN_REVIEW"


def test_run_pipeline_with_gates_pass_after_one_rewrite(monkeypatch, tmp_path: Path) -> None:
    """Gates fail on iter 1, pass on iter 2."""
    import agents.blogging.agent_implementations.blog_writing_process_v2 as v2

    monkeypatch.setattr(v2, "run_planning", lambda *a, **kw: _make_plan())
    monkeypatch.setattr(v2, "load_style_file", lambda *a, **kw: "ok")
    monkeypatch.setattr(v2, "load_brand_spec_prompt", lambda *a, **kw: "brand")
    monkeypatch.setattr(v2, "BlogWriterAgent", make_stub_writer_class())
    monkeypatch.setattr(v2, "BlogCopyEditorAgent", make_stub_editor_class())

    # Validator: FAIL first, PASS second
    state = {"i": 0}

    def validator_factory(wd, **kw):
        state["i"] += 1
        return _ValidatorStub(status="PASS" if state["i"] >= 2 else "FAIL")

    monkeypatch.setattr(v2, "run_validators_from_work_dir", validator_factory)

    from agents.blogging.blog_compliance_agent.models import ComplianceReport
    from agents.blogging.blog_fact_check_agent.models import FactCheckReport

    compliance_state = {"i": 0}

    class _Compliance:
        def __init__(self, *a, **kw):
            pass

        def run(self, *a, **kw):
            compliance_state["i"] += 1
            return ComplianceReport(
                status="PASS" if compliance_state["i"] >= 2 else "FAIL",
                violations=[],
                required_fixes=[] if compliance_state["i"] >= 2 else ["fix me"],
                notes=None,
            )

    fc_state = {"i": 0}

    class _FactCheck:
        def __init__(self, *a, **kw):
            pass

        def run(self, *a, **kw):
            fc_state["i"] += 1
            return FactCheckReport(
                claims_status="PASS",
                risk_status="PASS" if fc_state["i"] >= 2 else "FAIL",
                risk_flags=[] if fc_state["i"] >= 2 else ["x"],
                required_disclaimers=[],
                unverified_claims=[],
                claims=[],
            )

    monkeypatch.setattr(v2, "BlogComplianceAgent", _Compliance)
    monkeypatch.setattr(v2, "BlogFactCheckAgent", _FactCheck)

    from agents.blogging.blog_research_agent.models import ResearchBriefInput

    brief = ResearchBriefInput(brief="hi", max_results=5)
    _, _, status = v2.run_pipeline(
        brief,
        work_dir=tmp_path / "wd",
        run_gates=True,
        max_rewrite_iterations=3,
        draft_editor_iterations=1,
    )
    assert status == "PASS"


def _raising_gate(exc: Exception):
    """A gate-agent stub class whose ``run`` raises ``exc``."""

    class _Stub:
        def __init__(self, *a, **kw):
            pass

        def run(self, *a, **kw):
            raise exc

    return _Stub


def _run_gated_pipeline(v2, tmp_path):
    from agents.blogging.blog_research_agent.models import ResearchBriefInput

    brief = ResearchBriefInput(brief="hi", max_results=5)
    return v2.run_pipeline(
        brief,
        work_dir=tmp_path / "wd",
        run_gates=True,
        max_rewrite_iterations=1,
        draft_editor_iterations=1,
    )


def test_gate_factcheck_transient_error_propagates_unwrapped(monkeypatch, tmp_path: Path) -> None:
    """A transient LLM error from the fact-check gate propagates unwrapped (for Temporal retry)."""
    import pytest

    from llm_service import LLMTemporaryError

    v2 = _common_v2_setup(monkeypatch, validator_status="PASS")
    monkeypatch.setattr(v2, "BlogComplianceAgent", _stub_compliance("PASS"))
    monkeypatch.setattr(v2, "BlogFactCheckAgent", _raising_gate(LLMTemporaryError("503")))

    with pytest.raises(LLMTemporaryError):
        _run_gated_pipeline(v2, tmp_path)


def test_gate_factcheck_generic_error_maps_to_factcheckerror(monkeypatch, tmp_path: Path) -> None:
    """A non-transient error from the fact-check gate maps to FactCheckError."""
    import pytest
    from agents.blogging.shared.errors import FactCheckError

    v2 = _common_v2_setup(monkeypatch, validator_status="PASS")
    monkeypatch.setattr(v2, "BlogComplianceAgent", _stub_compliance("PASS"))
    monkeypatch.setattr(v2, "BlogFactCheckAgent", _raising_gate(RuntimeError("boom")))

    with pytest.raises(FactCheckError):
        _run_gated_pipeline(v2, tmp_path)


def test_gate_compliance_generic_error_maps_to_complianceerror(monkeypatch, tmp_path: Path) -> None:
    """A non-transient error from the compliance gate maps to ComplianceError."""
    import pytest
    from agents.blogging.shared.errors import ComplianceError

    v2 = _common_v2_setup(monkeypatch, validator_status="PASS")
    monkeypatch.setattr(v2, "BlogFactCheckAgent", _stub_factcheck("PASS", "PASS"))
    monkeypatch.setattr(v2, "BlogComplianceAgent", _raising_gate(RuntimeError("boom")))

    with pytest.raises(ComplianceError):
        _run_gated_pipeline(v2, tmp_path)


def test_both_gates_invoked_when_parallelized(monkeypatch, tmp_path: Path) -> None:
    """Both gates run (concurrently) and their PASS reports combine to status=PASS."""
    from agents.blogging.blog_compliance_agent.models import ComplianceReport
    from agents.blogging.blog_fact_check_agent.models import FactCheckReport

    calls = {"fact": 0, "compliance": 0}

    class _CountingFact:
        def __init__(self, *a, **kw):
            pass

        def run(self, *a, **kw):
            calls["fact"] += 1
            return FactCheckReport(
                claims_status="PASS",
                risk_status="PASS",
                risk_flags=[],
                required_disclaimers=[],
                unverified_claims=[],
                claims=[],
            )

    class _CountingCompliance:
        def __init__(self, *a, **kw):
            pass

        def run(self, *a, **kw):
            calls["compliance"] += 1
            return ComplianceReport(status="PASS", violations=[], required_fixes=[], notes="ok")

    v2 = _common_v2_setup(monkeypatch, validator_status="PASS")
    monkeypatch.setattr(v2, "BlogFactCheckAgent", _CountingFact)
    monkeypatch.setattr(v2, "BlogComplianceAgent", _CountingCompliance)

    _, _, status = _run_gated_pipeline(v2, tmp_path)
    assert status == "PASS"
    assert calls == {"fact": 1, "compliance": 1}


def test_gate_failure_drains_other_gate(monkeypatch, tmp_path: Path) -> None:
    """When one gate raises, the other still runs to completion before the error
    propagates — no abandoned worker that could overwrite a later attempt's artifact."""
    import pytest
    from agents.blogging.blog_compliance_agent.models import ComplianceReport

    from llm_service import LLMTemporaryError

    compliance_calls = {"n": 0}

    class _CountingCompliance:
        def __init__(self, *a, **kw):
            pass

        def run(self, *a, **kw):
            compliance_calls["n"] += 1
            return ComplianceReport(status="PASS", violations=[], required_fixes=[], notes="ok")

    v2 = _common_v2_setup(monkeypatch, validator_status="PASS")
    monkeypatch.setattr(v2, "BlogFactCheckAgent", _raising_gate(LLMTemporaryError("503")))
    monkeypatch.setattr(v2, "BlogComplianceAgent", _CountingCompliance)

    with pytest.raises(LLMTemporaryError):
        _run_gated_pipeline(v2, tmp_path)
    # Compliance ran to completion even though fact-check failed (drain, not fast-fail).
    assert compliance_calls["n"] == 1


def test_gates_builds_title_options_from_selected_title(monkeypatch, tmp_path: Path) -> None:
    """publishing_pack.json's title_options is built from ctx.selected_title when set.

    ``_run_title_selection`` is stubbed directly (rather than driven through a real
    job-store HITL round) — this file isolates the gates stage's own consumption of
    ``ctx.selected_title``; the job-store-to-context join is covered separately in
    ``test_pipeline_selected_title_e2e.py``.
    """
    from agents.blogging.agent_implementations.pipeline import planning_stage
    from agents.blogging.blog_research_agent.models import ResearchBriefInput
    from agents.blogging.shared.artifacts import read_artifact

    v2 = _common_v2_setup(monkeypatch, validator_status="PASS")
    monkeypatch.setattr(v2, "BlogComplianceAgent", _stub_compliance("PASS"))
    monkeypatch.setattr(v2, "BlogFactCheckAgent", _stub_factcheck("PASS", "PASS"))
    monkeypatch.setattr(
        planning_stage, "_run_title_selection", lambda *_a, **_kw: "The Loved Title"
    )

    work_dir = tmp_path / "wd"
    brief = ResearchBriefInput(brief="hi", max_results=5)
    _, _, status = v2.run_pipeline(
        brief,
        work_dir=work_dir,
        run_gates=True,
        max_rewrite_iterations=1,
        draft_editor_iterations=1,
    )
    assert status == "PASS"

    pack = read_artifact(work_dir, "publishing_pack.json")
    assert pack["title_options"] == ["The Loved Title"]


def test_gates_falls_back_to_plan_title_candidates_when_selection_skipped(
    monkeypatch, tmp_path: Path
) -> None:
    """No selected_title (no job store) → title_options falls back to the plan's
    first five title candidates, proving both the fallback and its [:5] truncation.
    """
    from agents.blogging.blog_research_agent.models import ResearchBriefInput
    from agents.blogging.shared.artifacts import read_artifact
    from agents.blogging.shared.content_plan import ContentPlanSection, TitleCandidate

    from ._content_plan_test_utils import make_content_plan, make_planning_phase_result

    plan = make_content_plan(
        overarching_topic="Topic",
        narrative_flow="Flow",
        sections=[ContentPlanSection(title="Intro", coverage_description="hook", order=0)],
        title_candidates=[
            TitleCandidate(title=f"Candidate {i}", probability_of_success=0.5) for i in range(6)
        ],
    )
    ppr = make_planning_phase_result(plan)

    v2 = _common_v2_setup(monkeypatch, validator_status="PASS")
    monkeypatch.setattr(v2, "run_planning", lambda *a, **kw: ppr)
    monkeypatch.setattr(v2, "BlogComplianceAgent", _stub_compliance("PASS"))
    monkeypatch.setattr(v2, "BlogFactCheckAgent", _stub_factcheck("PASS", "PASS"))
    # No job_id/job_updater passed to run_pipeline below, so run_planning_stage's
    # real (unstubbed) _run_title_selection short-circuits to None on its own guard.

    work_dir = tmp_path / "wd"
    brief = ResearchBriefInput(brief="hi", max_results=5)
    _, _, status = v2.run_pipeline(
        brief,
        work_dir=work_dir,
        run_gates=True,
        max_rewrite_iterations=1,
        draft_editor_iterations=1,
    )
    assert status == "PASS"

    pack = read_artifact(work_dir, "publishing_pack.json")
    assert pack["title_options"] == [f"Candidate {i}" for i in range(5)]


def test_gates_rewrite_revision_carries_selected_title(monkeypatch, tmp_path: Path) -> None:
    """The gates rewrite loop's ReviseWriterInput (gates_stage.py's own writer
    construction, separate from the draft stage's) carries ctx.selected_title.
    """
    from agents.blogging.agent_implementations.pipeline import planning_stage
    from agents.blogging.blog_compliance_agent.models import ComplianceReport
    from agents.blogging.blog_fact_check_agent.models import FactCheckReport
    from agents.blogging.blog_research_agent.models import ResearchBriefInput
    from agents.blogging.blog_writer_agent.models import WriterOutput

    captured: list = []

    class _CapturingWriter:
        def __init__(self, *a, **kw):
            pass

        def run(self, *a, **kw):
            return WriterOutput(draft="# Draft\n\nBody.")

        def revise(self, revise_input, *a, **kw):
            captured.append(revise_input)
            return WriterOutput(draft="# Revised\n\nBody.")

    # Validator/compliance/fact-check each FAIL on iteration 1, PASS on iteration 2 —
    # the same shape as test_run_pipeline_with_gates_pass_after_one_rewrite — so the
    # rewrite loop's revise() call fires exactly once before the pipeline passes.
    validator_state = {"i": 0}

    def validator_factory(wd, **kw):
        validator_state["i"] += 1
        return _ValidatorStub(status="PASS" if validator_state["i"] >= 2 else "FAIL")

    compliance_state = {"i": 0}

    class _Compliance:
        def __init__(self, *a, **kw):
            pass

        def run(self, *a, **kw):
            compliance_state["i"] += 1
            return ComplianceReport(
                status="PASS" if compliance_state["i"] >= 2 else "FAIL",
                violations=[],
                required_fixes=[] if compliance_state["i"] >= 2 else ["fix me"],
                notes=None,
            )

    fc_state = {"i": 0}

    class _FactCheck:
        def __init__(self, *a, **kw):
            pass

        def run(self, *a, **kw):
            fc_state["i"] += 1
            return FactCheckReport(
                claims_status="PASS",
                risk_status="PASS" if fc_state["i"] >= 2 else "FAIL",
                risk_flags=[] if fc_state["i"] >= 2 else ["x"],
                required_disclaimers=[],
                unverified_claims=[],
                claims=[],
            )

    v2 = _common_v2_setup(monkeypatch, validator_status="FAIL")
    monkeypatch.setattr(v2, "run_validators_from_work_dir", validator_factory)
    monkeypatch.setattr(v2, "BlogWriterAgent", _CapturingWriter)
    monkeypatch.setattr(v2, "BlogComplianceAgent", _Compliance)
    monkeypatch.setattr(v2, "BlogFactCheckAgent", _FactCheck)
    monkeypatch.setattr(
        planning_stage, "_run_title_selection", lambda *_a, **_kw: "The Loved Title"
    )

    brief = ResearchBriefInput(brief="hi", max_results=5)
    _, _, status = v2.run_pipeline(
        brief,
        work_dir=tmp_path / "wd",
        run_gates=True,
        max_rewrite_iterations=3,
        draft_editor_iterations=1,
    )
    assert status == "PASS"

    assert captured, "expected the gates rewrite loop to call revise() at least once"
    for revise_input in captured:
        assert revise_input.selected_title == "The Loved Title"
