"""Tests that ``run_draft_stage`` threads ``ctx.covered_sections`` into the writer.

The planning stage records which plan sections already received an author story, but
the writer only stops emitting a redundant ``[Author: ...]`` placeholder for them if
the draft stage reads that set off the context and hands it to every writer call.
There are six such call sites, and coverage has to reach all of them: a later
revision that dropped it would lose the suppression block and could reintroduce a
placeholder for a section whose story is sitting in the same prompt. These tests pin
each site — the three that run without a job store (initial draft, copy-edit
``ReviseWriterInput``, story-fill kwargs) and the three that need the HITL flow —
plus the ``set`` -> sorted-list normalization and the ``None``/empty no-ops.

Harness mirrors ``test_draft_stage_selected_title_threading.py``, which pins the same
sites for ``selected_title``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from agents.blogging.agent_implementations.pipeline.constants import (
    COPY_EDIT_ESCALATION_THRESHOLD,
)

from .conftest import make_stub_editor_class

COVERED_SECTIONS = {"Why it broke", "Intro"}
# The draft stage sorts the set: iteration order of a set is not stable across runs, and
# the writer's prompt has to be.
EXPECTED_ORDER = ["Intro", "Why it broke"]

# draft_editor_iterations needed to reach the copy-edit escalation branch. Derived from
# the production constant rather than hardcoded: the stage's loop sets
# copy_edit_num = iteration - 1 and escalates when copy_edit_num reaches the threshold,
# so the first escalating iteration is threshold + 1. Importing it means a change to the
# threshold moves this test with it instead of silently driving too few rounds.
_ESCALATION_ITERATIONS = COPY_EDIT_ESCALATION_THRESHOLD + 1


def _capturing_stub_writer_class(captured_inputs: list, *, uncertainty_questions: list) -> type:
    """A BlogWriterAgent stand-in recording every writer input it is handed.

    Preconditions:
        - ``captured_inputs`` is a list the caller owns and reads after the run.
        - ``uncertainty_questions`` is what ``identify_uncertainty_questions`` should
          return (empty to skip the uncertainty-answer revision path).
    Postconditions:
        - Returns a class (not an instance) suitable for monkeypatching a module's
          ``BlogWriterAgent`` reference. Every ``run``, ``revise`` or
          ``revise_from_user_feedback`` call appends a ``(kind, input)`` pair to
          ``captured_inputs`` — ``kind`` is ``"run"``, ``"revise"`` or
          ``"revise_from_user_feedback"`` — where ``input`` always exposes
          ``covered_sections``. ``revise`` is enumerated because it is how the batch
          copy-edit ``ReviseWriterInput`` is captured, one of the call sites this
          suite exists to pin.
    """
    from agents.blogging.blog_writer_agent.models import WriterOutput

    class _CapturingStubWriter:
        def __init__(self, *a, **kw):
            pass

        def run(self, draft_input, *a, **kw):
            captured_inputs.append(("run", draft_input))
            return WriterOutput(draft="# Draft\n\nBody.")

        def revise(self, revise_input, *a, **kw):
            captured_inputs.append(("revise", revise_input))
            return WriterOutput(draft="# Revised\n\nBody.")

        def revise_from_user_feedback(self, *a, covered_sections=None, **kw):
            # Every keyword is recorded, not just ``covered_sections``: this call shape
            # passes kwargs rather than a model, so anything dropped here is invisible to
            # the suite. A snapshot of ``elicited_stories`` taken before the story fill
            # once reached these rounds unnoticed for exactly that reason.
            captured_inputs.append(
                (
                    "revise_from_user_feedback",
                    SimpleNamespace(**kw, covered_sections=covered_sections),
                )
            )
            return WriterOutput(draft="# Revised\n\nBody.")

        def identify_uncertainty_questions(self, *a, **kw):
            return list(uncertainty_questions)

        def analyze_user_feedback_for_guideline_updates(self, *a, **kw):
            return []

        def generate_escalation_summary(self, *a, **kw):
            return "escalation summary"

    return _CapturingStubWriter


def _never_approving_editor_class() -> type:
    """A BlogCopyEditorAgent stub that never approves and never repeats itself.

    ``FeedbackTracker`` keys an issue by ``(category, severity, location)`` and calls the
    loop stalled once consecutive rounds overlap by >0.80 Jaccard. Varying ``location``
    each round keeps every signature distinct, so the loop reaches the escalation branch
    instead of breaking early on the stall check.
    """
    from agents.blogging.blog_copy_editor_agent.models import CopyEditorOutput, FeedbackItem

    class _StubEditor:
        def __init__(self, *a, **kw):
            self._calls = 0

        def run(self, *a, **kw):
            self._calls += 1
            return CopyEditorOutput(
                approved=False,
                summary=f"revise round {self._calls}",
                feedback_items=[
                    FeedbackItem(
                        category="style",
                        severity="must_fix",
                        location=f"paragraph {self._calls}",
                        issue=f"Distinct issue {self._calls}.",
                        suggestion=f"Fix issue {self._calls}.",
                    )
                ],
            )

    return _StubEditor


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


def _spy_fill_collecting_a_story(captured_kwargs: list, appended: str):
    """The same stand-in, but simulating a fill that actually collected a story.

    ``_spy_fill_story_placeholders`` returns ``elicited_stories_text`` unchanged, which is
    the one case that cannot detect a stale snapshot: the pre-fill and post-fill values are
    equal, so a later round reading either looks correct. This one appends, so a revision
    round carrying the pre-fill text is visibly missing ``appended``.
    """
    from agents.blogging.blog_writer_agent.models import WriterOutput

    def _fill(*, draft_text, draft_input_kwargs, elicited_stories_text, **_kw):
        captured_kwargs.append(draft_input_kwargs)
        return WriterOutput(draft=draft_text), f"{elicited_stories_text}\n\n{appended}"

    return _fill


def _install_fake_job_store(monkeypatch, *, draft_feedback_script: list, submitted_answers: list):
    """Monkeypatch the job-store surface so the HITL paths run without a real store.

    ``_wait_for_hitl`` is replaced wholesale (False = "user responded, not cancelled") so
    no test blocks on polling. ``draft_feedback_script`` is consumed one entry per
    ``get_user_draft_feedback`` call, falling back to an approval once exhausted so no
    review loop spins forever.
    """
    from agents.blogging.agent_implementations.pipeline import draft_stage as ds
    from agents.blogging.shared import blog_job_store

    monkeypatch.setattr(ds, "_wait_for_hitl", lambda *_a, **_kw: False)
    monkeypatch.setattr(ds, "add_blog_pending_questions", lambda *_a, **_kw: None)
    monkeypatch.setattr(ds, "record_guideline_updates", lambda *_a, **_kw: None)

    monkeypatch.setattr(blog_job_store, "request_draft_feedback", lambda *_a, **_kw: None)
    monkeypatch.setattr(blog_job_store, "is_waiting_for_draft_feedback", lambda *_a, **_kw: False)
    monkeypatch.setattr(
        blog_job_store, "get_blog_job", lambda *_a, **_kw: {"submitted_answers": submitted_answers}
    )
    feedback = iter(draft_feedback_script)
    monkeypatch.setattr(
        blog_job_store,
        "get_user_draft_feedback",
        lambda *_a, **_kw: next(feedback, {"approved": True}),
    )


def _run_stage(
    monkeypatch,
    *,
    covered_sections,
    editor_class=None,
    job_store: bool = False,
    draft_editor_iterations: int = 2,
) -> list[tuple[str, Any]]:
    """Drive ``run_draft_stage`` and return the ``(kind, input)`` pairs it produced."""
    import agents.blogging.agent_implementations.blog_writing_process_v2 as v2
    from agents.blogging.agent_implementations.pipeline.context import PipelineContext
    from agents.blogging.agent_implementations.pipeline.draft_stage import run_draft_stage
    from agents.blogging.blog_research_agent.models import ResearchBriefInput
    from agents.blogging.shared.content_profile import resolve_length_policy

    from ._content_plan_test_utils import make_minimal_planning_phase_result

    captured: list[tuple[str, Any]] = []
    questions = (
        [SimpleNamespace(question_id="q1", question="Which framing?", context="ctx")]
        if job_store
        else []
    )
    monkeypatch.setattr(v2, "load_style_file", lambda *a, **kw: "guidelines text")
    monkeypatch.setattr(
        v2,
        "BlogWriterAgent",
        _capturing_stub_writer_class(captured, uncertainty_questions=questions),
    )
    monkeypatch.setattr(v2, "BlogCopyEditorAgent", editor_class or make_stub_editor_class())

    ppr = make_minimal_planning_phase_result()
    ctx = PipelineContext(
        brief=ResearchBriefInput(brief="Topic about AI", audience="devs"),
        work_dir=None,
        llm_client=object(),
        length_policy=resolve_length_policy(),
        series_context=None,
        # Without a job store the HITL steps are skipped and the draft goes straight
        # to the automated copy-edit loop.
        job_id="job-1" if job_store else None,
        job_updater=(lambda **_kw: None) if job_store else None,
        draft_editor_iterations=draft_editor_iterations,
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
    _install_fake_job_store(monkeypatch, draft_feedback_script=[], submitted_answers=[])

    _run_stage(monkeypatch, covered_sections=COVERED_SECTIONS, job_store=True)

    assert fill_kwargs, "story-placeholder refill was never called"
    for kwargs in fill_kwargs:
        assert kwargs["covered_sections"] == EXPECTED_ORDER


def test_draft_stage_threads_covered_sections_through_hitl_revisions(monkeypatch) -> None:
    """The uncertainty-answer and author-feedback revisions receive coverage too.

    Both pass ``elicited_stories``; without the matching ``covered_sections`` the writer
    would drop the suppression block and could re-add an ``[Author: ...]`` placeholder
    for a section whose story is in that very prompt.
    """
    fill_kwargs: list = []
    from agents.blogging.agent_implementations.pipeline import draft_stage as ds

    monkeypatch.setattr(ds, "_fill_story_placeholders", _spy_fill_story_placeholders(fill_kwargs))
    _install_fake_job_store(
        monkeypatch,
        # First review round asks for changes (driving the author-feedback revision),
        # the second approves so the loop terminates.
        draft_feedback_script=[
            {"approved": False, "feedback": "Tighten the intro."},
            {"approved": True},
        ],
        submitted_answers=[{"question_id": "q1", "selected_answer": "The second framing."}],
    )

    captured = _run_stage(monkeypatch, covered_sections=COVERED_SECTIONS, job_store=True)

    revisions = [inp for kind, inp in captured if kind == "revise_from_user_feedback"]
    assert len(revisions) >= 2, f"expected both HITL revisions, got {len(revisions)}"
    for kind, writer_input in captured:
        assert writer_input.covered_sections == EXPECTED_ORDER, (
            f"{kind} call did not receive covered_sections"
        )


def test_draft_stage_threads_covered_sections_into_escalation_revision(monkeypatch) -> None:
    """The copy-edit escalation revision also receives coverage.

    Reaching it needs a job store plus an editor that never approves, so the loop runs
    to the escalation threshold.
    """
    fill_kwargs: list = []
    from agents.blogging.agent_implementations.pipeline import draft_stage as ds

    monkeypatch.setattr(ds, "_fill_story_placeholders", _spy_fill_story_placeholders(fill_kwargs))
    _install_fake_job_store(
        monkeypatch,
        # Approve at draft review so the run reaches the copy-edit loop, then return
        # feedback at the escalation prompt to drive its revision.
        draft_feedback_script=[
            {"approved": True},
            {"approved": False, "feedback": "Still needs a rewrite."},
        ],
        submitted_answers=[],
    )

    captured = _run_stage(
        monkeypatch,
        covered_sections=COVERED_SECTIONS,
        editor_class=_never_approving_editor_class(),
        job_store=True,
        draft_editor_iterations=_ESCALATION_ITERATIONS,
    )

    revisions = [inp for kind, inp in captured if kind == "revise_from_user_feedback"]
    assert revisions, "escalation revision never fired"
    for kind, writer_input in captured:
        assert writer_input.covered_sections == EXPECTED_ORDER, (
            f"{kind} call did not receive covered_sections"
        )


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


def test_draft_stage_threads_covered_sections_into_the_copy_edit_revision(monkeypatch) -> None:
    """The copy-edit loop's ``ReviseWriterInput`` carries coverage too.

    This one runs after the story fill and re-renders the whole draft, with no
    placeholder scan behind it, so a placeholder it reintroduces for a covered section
    would ship to the editor.
    """
    from agents.blogging.blog_copy_editor_agent.models import CopyEditorOutput, FeedbackItem

    class _EditorRequestingOneRevision:
        def __init__(self, *a, **kw):
            self._calls = 0

        def run(self, *a, **kw):
            self._calls += 1
            return CopyEditorOutput(
                approved=self._calls > 1,
                summary="revise" if self._calls == 1 else "ok",
                feedback_items=[]
                if self._calls > 1
                else [
                    FeedbackItem(
                        category="style",
                        severity="must_fix",
                        issue="Needs work.",
                        suggestion="Fix it.",
                    )
                ],
            )

    captured = _run_stage(
        monkeypatch,
        covered_sections=COVERED_SECTIONS,
        editor_class=_EditorRequestingOneRevision,
    )

    revisions = [inp for kind, inp in captured if kind == "revise"]
    assert revisions, "the copy-edit revision never fired"
    for revise_input in revisions:
        assert revise_input.covered_sections == EXPECTED_ORDER


def test_revisions_after_the_fill_carry_the_stories_it_collected(monkeypatch) -> None:
    """A story collected during the placeholder fill must reach the later revision rounds.

    ``_fill_story_placeholders`` rebinds ``elicited_stories_text`` with the narratives it
    collected. Every revision round after it has to read that rebound value, not a
    snapshot taken before the first draft — a round carrying the pre-fill text omits the
    story the author just supplied, and the writer's standing never-fabricate rule would
    then turn it back into the ``[Author: ...]`` placeholder the fill existed to answer.

    The sibling coverage tests cannot catch this: their fill spy returns the stories text
    unchanged, so pre-fill and post-fill are the same string.
    """
    collected = "[Story for section: Why it broke]\nThe rollback script was never tested."
    fill_kwargs: list = []
    from agents.blogging.agent_implementations.pipeline import draft_stage as ds

    monkeypatch.setattr(
        ds, "_fill_story_placeholders", _spy_fill_collecting_a_story(fill_kwargs, collected)
    )
    _install_fake_job_store(
        monkeypatch,
        draft_feedback_script=[
            {"approved": False, "feedback": "Tighten the intro."},
            {"approved": True},
        ],
        submitted_answers=[{"question_id": "q1", "selected_answer": "The second framing."}],
    )

    captured = _run_stage(monkeypatch, covered_sections=COVERED_SECTIONS, job_store=True)

    assert fill_kwargs, "story-placeholder fill never ran"
    post_fill = [
        (kind, inp) for kind, inp in captured if kind in ("revise_from_user_feedback", "revise")
    ]
    assert post_fill, "no revision round ran after the fill"
    for kind, writer_input in post_fill:
        assert collected in (writer_input.elicited_stories or ""), (
            f"{kind} carried pre-fill stories: the story collected during the fill is "
            f"missing from its prompt input"
        )
