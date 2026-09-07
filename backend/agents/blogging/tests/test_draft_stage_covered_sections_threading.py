"""Tests that ``run_draft_stage`` threads ``ctx.covered_sections`` into the writer.

The planning stage records which plan sections already received an author story, but
the writer only stops emitting a redundant ``[Author: ...]`` placeholder for them if
the draft stage reads that set off the context and hands it on. These tests pin both
hand-off points (the initial-draft ``WriterInput`` and the ``draft_input_kwargs`` given
to ``_fill_story_placeholders``), the ``set`` -> sorted-list normalization, and that the
``None`` the field still carries in Temporal mode is a safe no-op rather than a crash.

Harness mirrors ``test_draft_stage_selected_title_threading.py``, which pins the same
two call sites for ``selected_title``.
"""

from __future__ import annotations

from types import SimpleNamespace

from .conftest import make_stub_editor_class

COVERED_SECTIONS = {"Why it broke", "Intro"}
# The draft stage sorts the set: iteration order of a set is not stable across runs, and
# the writer's prompt has to be.
EXPECTED_ORDER = ["Intro", "Why it broke"]


def _capturing_stub_writer_class(captured_inputs: list) -> type:
    """A BlogWriterAgent stand-in recording every writer input it is handed.

    Preconditions:
        - ``captured_inputs`` is a list the caller owns and reads after the run.
    Postconditions:
        - Returns a class (not an instance) suitable for monkeypatching a module's
          ``BlogWriterAgent`` reference. Each ``run``/``revise_from_user_feedback``
          call appends a ``(kind, input)`` pair, where ``input`` exposes
          ``covered_sections``.
    """
    from agents.blogging.blog_writer_agent.models import WriterOutput

    class _CapturingStubWriter:
        def __init__(self, *a, **kw):
            pass

        def run(self, draft_input, *a, **kw):
            captured_inputs.append(("run", draft_input))
            return WriterOutput(draft="# Draft\n\nBody.")

        def revise(self, revise_input, *a, **kw):
            return WriterOutput(draft="# Revised\n\nBody.")

        def revise_from_user_feedback(self, *a, covered_sections=None, **kw):
            captured_inputs.append(
                (
                    "revise_from_user_feedback",
                    SimpleNamespace(covered_sections=covered_sections),
                )
            )
            return WriterOutput(draft="# Revised\n\nBody.")

        def identify_uncertainty_questions(self, *a, **kw):
            return []

        def analyze_user_feedback_for_guideline_updates(self, *a, **kw):
            return []

        def generate_escalation_summary(self, *a, **kw):
            return "escalation summary"

    return _CapturingStubWriter


def _spy_fill_story_placeholders(captured_kwargs: list):
    """Stand in for ``_fill_story_placeholders``, recording its ``draft_input_kwargs``.

    The real helper drives a ghost-writer interview; what is under test here is the dict
    the draft stage builds, which the helper forwards to ``revise_from_user_feedback``.
    """
    from agents.blogging.blog_writer_agent.models import WriterOutput

    def _fill(*, draft_text, draft_input_kwargs, elicited_stories_text, **_kw):
        captured_kwargs.append(draft_input_kwargs)
        return WriterOutput(draft=draft_text), elicited_stories_text

    return _fill


def _install_fake_job_store(monkeypatch):
    """Monkeypatch the job-store surface so the HITL paths run without a real store."""
    from agents.blogging.agent_implementations.pipeline import draft_stage as ds
    from agents.blogging.shared import blog_job_store

    monkeypatch.setattr(ds, "_wait_for_hitl", lambda *_a, **_kw: False)
    monkeypatch.setattr(ds, "add_blog_pending_questions", lambda *_a, **_kw: None)
    monkeypatch.setattr(ds, "record_guideline_updates", lambda *_a, **_kw: None)
    monkeypatch.setattr(blog_job_store, "request_draft_feedback", lambda *_a, **_kw: None)
    monkeypatch.setattr(blog_job_store, "is_waiting_for_draft_feedback", lambda *_a, **_kw: False)
    monkeypatch.setattr(
        blog_job_store, "get_blog_job", lambda *_a, **_kw: {"submitted_answers": []}
    )
    monkeypatch.setattr(
        blog_job_store, "get_user_draft_feedback", lambda *_a, **_kw: {"approved": True}
    )


def _run_stage(monkeypatch, *, covered_sections, job_store: bool = False) -> list:
    """Drive ``run_draft_stage`` and return the ``(kind, input)`` pairs it produced."""
    import agents.blogging.agent_implementations.blog_writing_process_v2 as v2
    from agents.blogging.agent_implementations.pipeline.context import PipelineContext
    from agents.blogging.agent_implementations.pipeline.draft_stage import run_draft_stage
    from agents.blogging.blog_research_agent.models import ResearchBriefInput
    from agents.blogging.shared.content_profile import resolve_length_policy

    from ._content_plan_test_utils import make_minimal_planning_phase_result

    captured: list = []
    monkeypatch.setattr(v2, "load_style_file", lambda *a, **kw: "guidelines text")
    monkeypatch.setattr(v2, "BlogWriterAgent", _capturing_stub_writer_class(captured))
    monkeypatch.setattr(v2, "BlogCopyEditorAgent", make_stub_editor_class())

    ppr = make_minimal_planning_phase_result()
    ctx = PipelineContext(
        brief=ResearchBriefInput(brief="Topic about AI", audience="devs"),
        work_dir=None,
        llm_client=object(),
        length_policy=resolve_length_policy(),
        series_context=None,
        job_id="job-1" if job_store else None,
        job_updater=(lambda **_kw: None) if job_store else None,
        draft_editor_iterations=2,
        max_rewrite_iterations=1,
        run_gates=False,
        planning_phase_result=ppr,
        plan=ppr.content_plan,
        elicited_stories_text="[Story for section: Intro]\nIt broke at 2am.",
        covered_sections=covered_sections,
    )

    assert run_draft_stage(ctx) is None
    return captured


def test_draft_stage_sorts_covered_sections_into_the_initial_writer_input(monkeypatch) -> None:
    """The set reaches the initial-draft ``WriterInput`` as a deterministically ordered list."""
    captured = _run_stage(monkeypatch, covered_sections=COVERED_SECTIONS)

    runs = [inp for kind, inp in captured if kind == "run"]
    assert runs, "the initial draft was never generated"
    assert runs[0].covered_sections == EXPECTED_ORDER


def test_draft_stage_threads_covered_sections_into_story_fill_kwargs(monkeypatch) -> None:
    """The ``draft_input_kwargs`` handed to ``_fill_story_placeholders`` carry the key, so
    the post-fill revision does not re-introduce a placeholder for a covered section."""
    fill_kwargs: list = []
    from agents.blogging.agent_implementations.pipeline import draft_stage as ds

    monkeypatch.setattr(ds, "_fill_story_placeholders", _spy_fill_story_placeholders(fill_kwargs))
    _install_fake_job_store(monkeypatch)

    _run_stage(monkeypatch, covered_sections=COVERED_SECTIONS, job_store=True)

    assert fill_kwargs, "story-placeholder refill was never called"
    for kwargs in fill_kwargs:
        assert kwargs["covered_sections"] == EXPECTED_ORDER


def test_draft_stage_treats_none_covered_sections_as_a_no_op(monkeypatch) -> None:
    """``None`` is the shape the field still has in Temporal mode, where planning's value
    does not cross the activity boundary. It must pass through as ``None`` rather than
    raising on ``sorted(None)``."""
    captured = _run_stage(monkeypatch, covered_sections=None)

    runs = [inp for kind, inp in captured if kind == "run"]
    assert runs, "the initial draft was never generated"
    assert runs[0].covered_sections is None


def test_draft_stage_treats_empty_covered_sections_as_a_no_op(monkeypatch) -> None:
    """An empty set is the documented no-op: nothing to suppress, so nothing is passed."""
    captured = _run_stage(monkeypatch, covered_sections=set())

    runs = [inp for kind, inp in captured if kind == "run"]
    assert runs, "the initial draft was never generated"
    assert runs[0].covered_sections is None
