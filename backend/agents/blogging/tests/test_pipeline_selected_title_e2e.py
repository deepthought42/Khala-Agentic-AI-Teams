"""Pipeline-level tests joining the two halves of title-selection threading.

``test_planning_stage_title_selection.py`` proves ``run_planning_stage`` sets
``ctx.selected_title`` from ``_run_title_selection``'s return value, with
``_run_title_selection`` itself stubbed. ``test_draft_stage_selected_title_threading.py``
proves ``run_draft_stage`` threads a pre-set ``ctx.selected_title`` into every
writer/revision call, with a hand-built ``ctx`` and a stub writer. Neither proves the
join: that the title the job store actually records via a real ``_run_title_selection``
HITL round is the exact string a writer input receives. These tests drive
``run_pipeline`` (or, for the real-writer case, ``run_draft_stage``) with
``_run_title_selection`` left real, closing that gap.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from .conftest import make_stub_editor_class

LOVED_TITLE = "The Loved Title"


def _make_title_loving_job_updater(job_id: str, loved_title: str):
    """Build a ``job_updater`` that persists real progress and loves the first
    title-selection round, so the real ``_run_title_selection`` resolves without
    ever blocking in its poll loop.

    Preconditions:
        - ``job_id`` identifies a job already created via ``create_blog_job``.
    Postconditions:
        - Returns a callable ``(**kwargs) -> None`` that first forwards to the
          production ``make_job_updater(job_id)`` closure (so phase/progress
          updates persist exactly as they do outside tests), then — the first
          time it observes ``waiting_for_title_selection=True`` — submits a
          "love" rating for ``loved_title`` via ``submit_title_ratings``. Later
          calls are inert once the rating has been submitted once.
    """
    from agents.blogging.shared import blog_job_store as bjs
    from agents.blogging.shared.run_pipeline_job import make_job_updater

    base_updater = make_job_updater(job_id)
    state = {"submitted": False}

    def job_updater(**kwargs) -> None:
        base_updater(**kwargs)
        if kwargs.get("waiting_for_title_selection") and not state["submitted"]:
            state["submitted"] = True
            bjs.submit_title_ratings(job_id, [{"title": loved_title, "rating": "love"}])

    return job_updater


def _capturing_stub_writer_class(captured: list, *, uncertainty_questions=()) -> type:
    """Build a ``BlogWriterAgent`` stand-in that records every writer input it is handed.

    Preconditions:
        - ``captured`` is a list the caller owns and reads after the run.
    Postconditions:
        - Returns a class (not an instance) suitable for monkeypatching a module's
          ``BlogWriterAgent`` reference. Every ``run``/``revise``/
          ``revise_from_user_feedback`` call appends a ``(kind, input)`` pair to
          ``captured``, where ``input`` always exposes ``.selected_title``.
    """
    from agents.blogging.blog_writer_agent.models import WriterOutput

    class _CapturingStubWriter:
        def __init__(self, *a, **kw):
            pass

        def run(self, draft_input, *a, **kw):
            captured.append(("run", draft_input))
            return WriterOutput(draft="# Draft\n\nBody.")

        def revise(self, revise_input, *a, **kw):
            captured.append(("revise", revise_input))
            return WriterOutput(draft="# Revised\n\nBody.")

        def revise_from_user_feedback(self, *a, selected_title=None, **kw):
            captured.append(
                ("revise_from_user_feedback", SimpleNamespace(selected_title=selected_title))
            )
            return WriterOutput(draft="# Revised\n\nBody.")

        def identify_uncertainty_questions(self, *a, **kw):
            return list(uncertainty_questions)

        def analyze_user_feedback_for_guideline_updates(self, *a, **kw):
            return []

        def generate_escalation_summary(self, *a, **kw):
            return ""

    return _CapturingStubWriter


def _stub_planning(monkeypatch, *, title: str):
    """Stub content planning and story elicitation so ``run_planning_stage`` reaches
    its real title-selection call without an LLM or a ghost-writer interview.

    ``_run_title_selection`` itself is left real — that call is the join this
    module's tests exist to prove.

    Preconditions:
        - None.
    Postconditions:
        - ``run_planning`` returns a single-candidate ``PlanningPhaseResult`` whose
          sole title is ``title``; story-gap finding and story-bank lookup both
          return empty, so no story elicitation runs.
        - Returns the stubbed ``PlanningPhaseResult``.
    """
    import agents.blogging.agent_implementations.blog_writing_process_v2 as v2
    from agents.blogging import ghost_writer_agent
    from agents.blogging.shared import story_bank

    from ._content_plan_test_utils import make_minimal_planning_phase_result

    ppr = make_minimal_planning_phase_result(title=title)
    monkeypatch.setattr(v2, "run_planning", lambda *_a, **_kw: ppr)
    monkeypatch.setattr(
        ghost_writer_agent.GhostWriterElicitationAgent, "find_story_gaps", lambda self, _plan: []
    )
    monkeypatch.setattr(story_bank, "find_relevant_stories", lambda *_a, **_kw: [])
    return ppr


def _bypass_hitl_waits(monkeypatch):
    """Bypass every outline/draft-review HITL wait in both stages so they never block.

    Patches ``planning_stage._wait_for_hitl`` and ``draft_stage._wait_for_hitl`` —
    each stage's own module-level import of the shared helper — which leaves
    ``_common._wait_for_hitl`` (used internally by the real ``_run_title_selection``)
    untouched.

    Preconditions:
        - None.
    Postconditions:
        - Both stages' ``_wait_for_hitl`` always return ``False`` (never terminal,
          never blocks/sleeps); the real HITL wait used by title selection is
          unaffected.
    """
    from agents.blogging.agent_implementations.pipeline import draft_stage, planning_stage

    monkeypatch.setattr(planning_stage, "_wait_for_hitl", lambda *_a, **_kw: False)
    monkeypatch.setattr(draft_stage, "_wait_for_hitl", lambda *_a, **_kw: False)


def _neutralize_story_placeholder_fill(monkeypatch):
    """No-op ``draft_stage._fill_story_placeholders`` for job-store-backed runs.

    With ``job_id``/``job_updater`` set, ``run_draft_stage`` always calls this
    helper for real; none of this module's stub drafts contain ``[Author: ...]``
    placeholders, so the real helper would already no-op, but replacing it removes
    an unrelated moving part rather than relying on that behavior implicitly.

    Preconditions:
        - None.
    Postconditions:
        - ``draft_stage._fill_story_placeholders`` returns
          ``(WriterOutput(draft=draft_text), elicited_stories_text)`` unchanged for
          any call.
    """
    from agents.blogging.agent_implementations.pipeline import draft_stage as ds
    from agents.blogging.blog_writer_agent.models import WriterOutput

    def _noop_fill(**kw):
        return WriterOutput(draft=kw["draft_text"]), kw["elicited_stories_text"]

    monkeypatch.setattr(ds, "_fill_story_placeholders", _noop_fill)


def test_run_pipeline_threads_job_store_title_into_writer(monkeypatch) -> None:
    """The title ``_run_title_selection`` records in the job store is the exact
    title ``WriterInput.selected_title`` carries into the writer's initial draft.
    """
    import agents.blogging.agent_implementations.blog_writing_process_v2 as v2
    from agents.blogging.blog_research_agent.models import ResearchBriefInput
    from agents.blogging.shared import blog_job_store as bjs

    _stub_planning(monkeypatch, title=LOVED_TITLE)
    _bypass_hitl_waits(monkeypatch)
    _neutralize_story_placeholder_fill(monkeypatch)

    monkeypatch.setattr(v2, "load_style_file", lambda *a, **kw: "guidelines text")
    captured: list = []
    monkeypatch.setattr(v2, "BlogWriterAgent", _capturing_stub_writer_class(captured))
    monkeypatch.setattr(v2, "BlogCopyEditorAgent", make_stub_editor_class())

    monkeypatch.setattr(bjs, "request_draft_feedback", lambda *_a, **_kw: None)
    monkeypatch.setattr(bjs, "is_waiting_for_draft_feedback", lambda *_a, **_kw: False)
    monkeypatch.setattr(bjs, "get_user_draft_feedback", lambda *_a, **_kw: {"approved": True})

    job_id = str(uuid.uuid4())[:8]
    bjs.create_blog_job(job_id, "brief")
    job_updater = _make_title_loving_job_updater(job_id, LOVED_TITLE)

    brief = ResearchBriefInput(brief="Topic about AI", audience="devs")
    _, _, status = v2.run_pipeline(
        brief,
        work_dir=None,
        run_gates=False,
        draft_editor_iterations=1,
        llm_client=object(),
        job_id=job_id,
        job_updater=job_updater,
    )

    assert status == "PASS"
    recorded_title = bjs.get_blog_job(job_id)["selected_title"]
    assert recorded_title == LOVED_TITLE
    assert [kind for kind, _ in captured] == ["run"]
    for _kind, writer_input in captured:
        assert writer_input.selected_title == recorded_title


def test_run_pipeline_threads_selected_title_into_revisions(monkeypatch) -> None:
    """Both a copy-edit-loop ``ReviseWriterInput`` and an interactive-review
    ``revise_from_user_feedback`` call carry the same job-store-recorded title.
    """
    import agents.blogging.agent_implementations.blog_writing_process_v2 as v2
    from agents.blogging.blog_research_agent.models import ResearchBriefInput
    from agents.blogging.shared import blog_job_store as bjs

    _stub_planning(monkeypatch, title=LOVED_TITLE)
    _bypass_hitl_waits(monkeypatch)
    _neutralize_story_placeholder_fill(monkeypatch)

    monkeypatch.setattr(v2, "load_style_file", lambda *a, **kw: "guidelines text")
    captured: list = []
    monkeypatch.setattr(v2, "BlogWriterAgent", _capturing_stub_writer_class(captured))
    # Never approves: the sole copy-edit pass (iteration 2) forces one ReviseWriterInput.
    monkeypatch.setattr(v2, "BlogCopyEditorAgent", make_stub_editor_class(approved=False))

    monkeypatch.setattr(bjs, "request_draft_feedback", lambda *_a, **_kw: None)
    monkeypatch.setattr(bjs, "is_waiting_for_draft_feedback", lambda *_a, **_kw: False)
    feedback_script = iter(
        [
            {"approved": True},  # outline approval (planning stage)
            {"approved": False, "feedback": "Tighten the intro."},  # draft review round 1
            {"approved": True},  # draft review round 2
        ]
    )
    monkeypatch.setattr(
        bjs,
        "get_user_draft_feedback",
        lambda *_a, **_kw: next(feedback_script, {"approved": True}),
    )

    job_id = str(uuid.uuid4())[:8]
    bjs.create_blog_job(job_id, "brief")
    job_updater = _make_title_loving_job_updater(job_id, LOVED_TITLE)

    brief = ResearchBriefInput(brief="Topic about AI", audience="devs")
    _, _, status = v2.run_pipeline(
        brief,
        work_dir=None,
        run_gates=False,
        draft_editor_iterations=2,
        llm_client=object(),
        job_id=job_id,
        job_updater=job_updater,
    )

    assert status == "PASS"
    recorded_title = bjs.get_blog_job(job_id)["selected_title"]
    assert recorded_title == LOVED_TITLE

    kinds = [kind for kind, _ in captured]
    assert "revise_from_user_feedback" in kinds, f"expected a HITL revision, got {kinds}"
    assert "revise" in kinds, f"expected a copy-edit ReviseWriterInput revision, got {kinds}"
    for kind, writer_input in captured:
        assert writer_input.selected_title == recorded_title, f"{kind} carried the wrong title"


def test_run_pipeline_without_job_store_keeps_selected_title_none(monkeypatch) -> None:
    """With no ``job_id``/``job_updater``, title selection never runs and every
    writer input's ``selected_title`` stays ``None`` — the CLI / no-job-store path.
    """
    import agents.blogging.agent_implementations.blog_writing_process_v2 as v2
    from agents.blogging.blog_research_agent.models import ResearchBriefInput

    _stub_planning(monkeypatch, title="Unused Candidate Title")

    monkeypatch.setattr(v2, "load_style_file", lambda *a, **kw: "guidelines text")
    captured: list = []
    monkeypatch.setattr(v2, "BlogWriterAgent", _capturing_stub_writer_class(captured))
    monkeypatch.setattr(v2, "BlogCopyEditorAgent", make_stub_editor_class())

    brief = ResearchBriefInput(brief="Topic about AI", audience="devs")
    _, _, status = v2.run_pipeline(
        brief,
        work_dir=None,
        run_gates=False,
        draft_editor_iterations=1,
        llm_client=object(),
    )

    assert status == "PASS"
    assert captured
    for _kind, writer_input in captured:
        assert writer_input.selected_title is None


def test_draft_stage_real_writer_emits_author_chosen_title_prompts(monkeypatch) -> None:
    """With the real ``BlogWriterAgent`` (not a stub), ``ctx.selected_title`` reaches
    the actual prompt text at all three previously-dead branches: the initial draft
    (``agent.py``'s ``run()``), the interactive-review revision (``agent.py``'s
    ``revise_from_user_feedback()``), and the copy-edit-loop revision
    (``revision.py``'s ``build_revise_all_items_prompt``, via ``agent.py``'s
    ``revise()``).
    """
    import agents.blogging.agent_implementations.blog_writing_process_v2 as v2
    from agents.blogging.agent_implementations.pipeline import draft_stage as ds
    from agents.blogging.agent_implementations.pipeline.context import PipelineContext
    from agents.blogging.agent_implementations.pipeline.draft_stage import run_draft_stage
    from agents.blogging.blog_copy_editor_agent.models import FeedbackItem
    from agents.blogging.blog_research_agent.models import ResearchBriefInput
    from agents.blogging.blog_writer_agent.agent import BlogWriterAgent
    from agents.blogging.shared import blog_job_store as bjs
    from agents.blogging.shared.content_profile import resolve_length_policy

    from llm_service import DummyLLMClient

    from ._content_plan_test_utils import make_minimal_planning_phase_result

    captured_prompts: list[str] = []

    def fake_call_text(self, p, system_prompt=""):
        captured_prompts.append(p)
        return '{"draft": 0}\n---DRAFT---\n# Body\n\nSome revised body.\n'

    def fake_call_agent_json(self, p, system_prompt=""):
        return {"summary": "Fix the opening.", "changes": [], "risks": []}

    monkeypatch.setattr(BlogWriterAgent, "_call_text", fake_call_text)
    monkeypatch.setattr(BlogWriterAgent, "_call_agent_json", fake_call_agent_json)
    monkeypatch.setattr(
        BlogWriterAgent, "_self_review", lambda self, d, allowed_claims_section="": d
    )
    # Neutralize the two side-methods unrelated to the prompt branches under test —
    # both call the LLM for a different purpose than run()/revise()/
    # revise_from_user_feedback(), and a real call would pollute captured_prompts
    # (or fail to parse fake_call_agent_json's revision-plan-shaped canned response).
    monkeypatch.setattr(
        BlogWriterAgent, "identify_uncertainty_questions", lambda self, *a, **kw: []
    )
    monkeypatch.setattr(
        BlogWriterAgent, "analyze_user_feedback_for_guideline_updates", lambda self, *a, **kw: []
    )

    monkeypatch.setattr(v2, "load_style_file", lambda *a, **kw: "guidelines text")
    monkeypatch.setattr(
        v2,
        "BlogCopyEditorAgent",
        make_stub_editor_class(
            approved=False,
            feedback_items=[
                FeedbackItem(
                    category="style",
                    severity="must_fix",
                    issue="Needs work.",
                    suggestion="Fix it.",
                )
            ],
        ),
    )

    monkeypatch.setattr(ds, "_wait_for_hitl", lambda *_a, **_kw: False)
    _neutralize_story_placeholder_fill(monkeypatch)

    monkeypatch.setattr(bjs, "request_draft_feedback", lambda *_a, **_kw: None)
    monkeypatch.setattr(bjs, "is_waiting_for_draft_feedback", lambda *_a, **_kw: False)
    feedback_script = iter(
        [
            {"approved": False, "feedback": "Tighten the intro."},
            {"approved": True},
        ]
    )
    monkeypatch.setattr(
        bjs,
        "get_user_draft_feedback",
        lambda *_a, **_kw: next(feedback_script, {"approved": True}),
    )

    ppr = make_minimal_planning_phase_result()
    ctx = PipelineContext(
        brief=ResearchBriefInput(brief="Topic about AI", audience="devs"),
        work_dir=None,
        llm_client=DummyLLMClient(),
        length_policy=resolve_length_policy(),
        series_context=None,
        job_id="job-1",
        job_updater=lambda **_kw: None,
        draft_editor_iterations=2,
        max_rewrite_iterations=1,
        run_gates=False,
        planning_phase_result=ppr,
        plan=ppr.content_plan,
        selected_title=LOVED_TITLE,
    )

    assert run_draft_stage(ctx) is None

    assert len(captured_prompts) == 3, (
        f"expected run() + revise_from_user_feedback() + revise(), got {len(captured_prompts)}"
    )
    assert "AUTHOR-CHOSEN TITLE (NON-NEGOTIABLE)" in captured_prompts[0]
    assert LOVED_TITLE in captured_prompts[0]
    assert "AUTHOR-CHOSEN TITLE (preserve this exact H1)" in captured_prompts[1]
    assert LOVED_TITLE in captured_prompts[1]
    assert "AUTHOR-CHOSEN TITLE (preserve this exact H1)" in captured_prompts[2]
    assert LOVED_TITLE in captured_prompts[2]
