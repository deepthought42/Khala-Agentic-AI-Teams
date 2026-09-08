"""Tests that ``run_gates_stage`` threads ``ctx.covered_sections`` into its rewrite.

The gate-driven rewrite is the last writer call in the pipeline and the one furthest
from the story fill: it re-renders the whole draft with the elicited stories present,
and nothing downstream re-scans for ``[Author: ...]`` placeholders. Without the
coverage list its prompt carries the stories but no statement of which sections they
satisfy, so the system prompt's standing instruction to insert a placeholder when no
story was supplied can put one back on a section whose story is in that very prompt.

Drives ``run_gates_stage`` directly rather than through ``run_pipeline``: the call
site under test is one ``ReviseWriterInput`` construction, and a failing gate is all
that is needed to reach it.
"""

from __future__ import annotations

COVERED_SECTIONS = {"Why it broke", "Intro"}
EXPECTED_ORDER = ["Intro", "Why it broke"]


def _capturing_stub_writer_class(captured: list) -> type:
    """A BlogWriterAgent stand-in recording every ``ReviseWriterInput`` it is handed.

    Preconditions:
        - ``captured`` is a list the caller owns and reads after the run.
    Postconditions:
        - Returns a class (not an instance) suitable for monkeypatching the shim's
          ``BlogWriterAgent``; every ``revise`` call appends its input to ``captured``.
    """
    from agents.blogging.blog_writer_agent.models import WriterOutput

    class _CapturingStubWriter:
        def __init__(self, *a, **kw):
            pass

        def revise(self, revise_input, *a, **kw):
            captured.append(revise_input)
            return WriterOutput(draft="# Rewritten\n\nBody.")

        def run(self, *a, **kw):
            return WriterOutput(draft="# Draft\n\nBody.")

    return _CapturingStubWriter


class _ValidatorStub:
    def __init__(self, status: str = "PASS"):
        self.status = status
        self.checks = []


def _run_gates(monkeypatch, tmp_path, *, covered_sections) -> list:
    """Drive ``run_gates_stage`` with a failing compliance gate and return revise inputs."""
    import agents.blogging.agent_implementations.blog_writing_process_v2 as v2
    from agents.blogging.agent_implementations.pipeline.context import PipelineContext
    from agents.blogging.agent_implementations.pipeline.gates_stage import run_gates_stage
    from agents.blogging.blog_compliance_agent.models import ComplianceReport, Violation
    from agents.blogging.blog_fact_check_agent.models import FactCheckReport
    from agents.blogging.blog_research_agent.models import ResearchBriefInput
    from agents.blogging.blog_writer_agent.models import WriterOutput
    from agents.blogging.shared.content_profile import resolve_length_policy

    from ._content_plan_test_utils import make_minimal_planning_phase_result

    captured: list = []

    class _FailingCompliance:
        def __init__(self, *a, **kw):
            pass

        def run(self, *a, **kw):
            return ComplianceReport(
                status="FAIL",
                violations=[Violation(rule_id="tone-1", description="Off-brand opener.")],
                required_fixes=["Rewrite the opener in the brand voice."],
                notes="",
            )

    class _PassingFactCheck:
        def __init__(self, *a, **kw):
            pass

        def run(self, *a, **kw):
            return FactCheckReport(
                claims_status="PASS",
                risk_status="PASS",
                risk_flags=[],
                required_disclaimers=[],
                unverified_claims=[],
                claims=[],
            )

    monkeypatch.setattr(v2, "load_style_file", lambda *a, **kw: "ok")
    monkeypatch.setattr(v2, "load_brand_spec_prompt", lambda *a, **kw: "brand")
    monkeypatch.setattr(v2, "BlogWriterAgent", _capturing_stub_writer_class(captured))
    monkeypatch.setattr(v2, "BlogComplianceAgent", _FailingCompliance)
    monkeypatch.setattr(v2, "BlogFactCheckAgent", _PassingFactCheck)
    monkeypatch.setattr(
        v2, "run_validators_from_work_dir", lambda wd, **kw: _ValidatorStub(status="PASS")
    )

    ppr = make_minimal_planning_phase_result()
    ctx = PipelineContext(
        brief=ResearchBriefInput(brief="Topic about AI", audience="devs"),
        work_dir=tmp_path,
        llm_client=object(),
        length_policy=resolve_length_policy(),
        series_context=None,
        job_id=None,
        job_updater=None,
        draft_editor_iterations=1,
        max_rewrite_iterations=2,
        run_gates=True,
        planning_phase_result=ppr,
        plan=ppr.content_plan,
        elicited_stories_text="[Story for section: Intro]\nIt broke at 2am.",
        covered_sections=covered_sections,
        draft_result=WriterOutput(draft="# Draft\n\nBody."),
    )

    assert run_gates_stage(ctx) is None
    return captured


def test_gates_rewrite_receives_sorted_covered_sections(monkeypatch, tmp_path) -> None:
    """The set reaches the rewrite's ``ReviseWriterInput`` in the same sorted form the
    draft stage produces, so both stages name the covered sections identically."""
    captured = _run_gates(monkeypatch, tmp_path, covered_sections=COVERED_SECTIONS)

    assert captured, "the gate-driven rewrite never fired"
    for revise_input in captured:
        assert revise_input.covered_sections == EXPECTED_ORDER


def test_gates_rewrite_treats_none_covered_sections_as_a_no_op(monkeypatch, tmp_path) -> None:
    """``None`` is the shape the field has in Temporal mode; it must pass through
    rather than raising on ``sorted(None)``."""
    captured = _run_gates(monkeypatch, tmp_path, covered_sections=None)

    assert captured, "the gate-driven rewrite never fired"
    for revise_input in captured:
        assert revise_input.covered_sections is None
