"""Tests for threading ``covered_sections`` into the writer's prompts.

The draft prompt tells the model to emit an ``[Author: ...]`` placeholder whenever it
lacks a story. ``covered_sections`` names the plan sections that already have one, so
the model stops asking for material the author supplied during planning.

The change sits directly on an anti-fabrication guardrail, so these tests pin the
*narrowing* (a covered section gets no placeholder instruction) alongside everything
that must not move: in the draft prompt the two "NEVER fabricate" clauses and the
FINAL CHECK scan stay verbatim for every input, an absent or empty field leaves either
prompt byte-identical to what it was before the field existed, and a set of covered
sections with no stories to back it renders nothing at all.

The guardrail-verbatim assertions are scoped to ``run()`` deliberately: that quality
checklist exists only in the draft prompt. ``revise_from_user_feedback`` builds from
``USER_FEEDBACK_REVISION_INSTRUCTIONS`` and never carries those clauses, so its
never-fabricate rule comes from the system prompt (``prompts.py``'s
``WRITING_SYSTEM_PROMPT``, which both paths share) rather than from anything this suite
could assert on the revise prompt's text.
"""

from __future__ import annotations

from .conftest import make_writer_agent

STORIES = (
    "[Story for section: Intro]\nI once shipped a migration at 2am and it took the site down.\n\n"
    "[Story for section: Why it broke]\nThe rollback script had never been run against prod."
)

# The exact guardrail sentences from the draft prompt's quality checklist. Asserted
# verbatim: this feature must narrow where placeholders appear without rewording the
# instructions that stop the model inventing the author's experiences.
NEVER_FABRICATE_HOOK = (
    "first-person opening hook from author-provided stories (or placeholder if none "
    "provided, NEVER fabricate)"
)
NEVER_FABRICATE_FAILURE = (
    "at least one transparent-failure moment from author stories (or placeholder "
    "if none, NEVER fabricate)"
)
FINAL_CHECK = (
    "FINAL CHECK: scan every 'I' or 'my' sentence, if it describes a specific event "
    "not from the AUTHOR'S PERSONAL STORIES section, replace it with a placeholder."
)

SUPPRESSION_HEADER = "SECTIONS ALREADY COVERED BY AN AUTHOR STORY:"
SUPPRESSION_INSTRUCTION = "do not emit an [Author: ...] placeholder for those sections"


def _writer_input(**overrides):
    """A ``WriterInput`` over a three-section plan, via the shared builder.

    The third section ("What we changed") deliberately never has a story, so the
    suppression block can be asserted to name only the two that do.
    """
    from agents.blogging.shared.content_plan import ContentPlanSection

    from ._content_plan_test_utils import make_writer_input

    return make_writer_input(
        sections=[
            ContentPlanSection(title="Intro", coverage_description="hook", order=0),
            ContentPlanSection(title="Why it broke", coverage_description="failure", order=1),
            ContentPlanSection(title="What we changed", coverage_description="fix", order=2),
        ],
        **overrides,
    )


def _capture_prompts(monkeypatch) -> list[str]:
    """Record every prompt the writer sends, in call order.

    A list rather than a single slot because ``run()`` makes more than one LLM call:
    the draft generation is followed by ``_self_review``, whose prompt would otherwise
    overwrite the one under test and make these assertions pass vacuously.
    """
    from agents.blogging.blog_writer_agent.agent import BlogWriterAgent

    prompts: list[str] = []

    def fake_call(self, prompt, system_prompt=""):
        prompts.append(prompt)
        return '{"draft": 0}\n---DRAFT---\n# Out\nBody.'

    monkeypatch.setattr(BlogWriterAgent, "_call_text", fake_call)
    return prompts


def _capture_run_prompt(monkeypatch, **overrides) -> str:
    """Run the writer and return the initial-draft prompt (the first LLM call)."""
    prompts = _capture_prompts(monkeypatch)
    make_writer_agent().run(_writer_input(**overrides))
    assert prompts, "the writer made no LLM call"
    return prompts[0]


def _capture_revise_prompt(monkeypatch, **kwargs) -> str:
    """Same, for the post-fill ``revise_from_user_feedback`` path."""
    prompts = _capture_prompts(monkeypatch)
    make_writer_agent().revise_from_user_feedback(
        draft="# Draft\n\nBody.",
        user_feedback="Weave in the stories.",
        content_plan_text="- Intro\n- Why it broke",
        **kwargs,
    )
    assert prompts, "the writer made no LLM call"
    return prompts[0]


def _suppression_line(text: str) -> str:
    """The single line naming the covered sections, for exact-match assertions.

    Asserting this line whole rather than a substring of it is what makes the
    "skipped" half of the renderer's contract testable: ``f"{HEADER} Intro" in text``
    also passes for ``f"{HEADER} Intro, None, 7"``.
    """
    return next(line for line in text.splitlines() if line.startswith(SUPPRESSION_HEADER))


# ---------------------------------------------------------------------------
# _render_covered_sections_section — the renderer both prompts share
# ---------------------------------------------------------------------------


def test_render_returns_block_naming_covered_sections() -> None:
    from agents.blogging.blog_writer_agent.agent import _render_covered_sections_section

    out = _render_covered_sections_section(["Intro", "Why it broke"], STORIES)
    assert _suppression_line(out) == f"{SUPPRESSION_HEADER} Intro, Why it broke"
    assert SUPPRESSION_INSTRUCTION in out


def test_render_sorts_and_deduplicates_titles() -> None:
    """Callers derive this list from a ``set``, so the renderer owns the stable order."""
    from agents.blogging.blog_writer_agent.agent import _render_covered_sections_section

    out = _render_covered_sections_section(
        ["Why it broke", "Intro", "Why it broke", "  Intro  "], STORIES
    )
    assert _suppression_line(out) == f"{SUPPRESSION_HEADER} Intro, Why it broke"


def test_render_skips_unusable_entries() -> None:
    """A malformed entry is skipped, never raised on: a bad title must not fail a draft.

    The header line is asserted *exactly*. A substring check would pass even if the
    renderer regressed to stringifying junk ("...: Intro, None, 7" contains
    "...: Intro"), which on this guardrail-adjacent block would name sections as
    covered that have no story behind them.
    """
    from agents.blogging.blog_writer_agent.agent import _render_covered_sections_section

    out = _render_covered_sections_section(["Intro", "", "   ", None, 7], STORIES)
    assert _suppression_line(out) == f"{SUPPRESSION_HEADER} Intro"


def test_render_returns_empty_for_absent_or_empty_sections() -> None:
    from agents.blogging.blog_writer_agent.agent import _render_covered_sections_section

    assert _render_covered_sections_section(None, STORIES) == ""
    assert _render_covered_sections_section([], STORIES) == ""
    assert _render_covered_sections_section(["", "  "], STORIES) == ""


def test_render_returns_empty_without_stories_to_back_the_claim() -> None:
    """The load-bearing gate: never assert a story the prompt does not also carry."""
    from agents.blogging.blog_writer_agent.agent import _render_covered_sections_section

    assert _render_covered_sections_section(["Intro"], None) == ""
    assert _render_covered_sections_section(["Intro"], "") == ""
    assert _render_covered_sections_section(["Intro"], "   \n  ") == ""


def test_render_block_restates_the_never_fabricate_fallbacks() -> None:
    """The block must narrow placeholder emission without reading as licence to invent."""
    from agents.blogging.blog_writer_agent.agent import _render_covered_sections_section

    out = _render_covered_sections_section(["Intro"], STORIES)
    assert "for every section not named above, the never-fabricate rules apply unchanged" in out
    assert "emit the placeholder for it rather than inventing one" in out
    # The writing guidelines ban em/en dashes; the prompt should not model what it forbids.
    assert "—" not in out and "–" not in out


# ---------------------------------------------------------------------------
# run() — the initial draft prompt
# ---------------------------------------------------------------------------


def test_run_names_covered_sections_and_leaves_uncovered_ones_alone(monkeypatch) -> None:
    """The AC's core assertion: a covered section is named and suppressed, an uncovered
    section is not named, and the never-fabricate instructions that still govern it are
    present verbatim."""
    prompt = _capture_run_prompt(
        monkeypatch, elicited_stories=STORIES, covered_sections=["Intro", "Why it broke"]
    )

    # Exact line, so the third plan section ("What we changed") cannot be named as
    # covered: it has no story, and naming it would be the fabrication risk itself.
    assert _suppression_line(prompt) == f"{SUPPRESSION_HEADER} Intro, Why it broke"
    assert SUPPRESSION_INSTRUCTION in prompt
    # ...and the rules that still apply to it are untouched.
    assert NEVER_FABRICATE_HOOK in prompt
    assert NEVER_FABRICATE_FAILURE in prompt
    assert FINAL_CHECK in prompt


def test_run_prompt_is_byte_identical_when_covered_sections_absent(monkeypatch) -> None:
    baseline = _capture_run_prompt(monkeypatch, elicited_stories=STORIES)
    with_none = _capture_run_prompt(monkeypatch, elicited_stories=STORIES, covered_sections=None)
    assert with_none == baseline


def test_run_prompt_is_byte_identical_when_covered_sections_empty(monkeypatch) -> None:
    baseline = _capture_run_prompt(monkeypatch, elicited_stories=STORIES)
    with_empty = _capture_run_prompt(monkeypatch, elicited_stories=STORIES, covered_sections=[])
    assert with_empty == baseline


def test_run_omits_suppression_without_elicited_stories(monkeypatch) -> None:
    """Covered sections with no stories block renders nothing, and the never-fabricate
    instructions stay intact — this is the input under which a suppression instruction
    could otherwise read as permission to invent the missing story."""
    baseline = _capture_run_prompt(monkeypatch)
    prompt = _capture_run_prompt(monkeypatch, covered_sections=["Intro", "Why it broke"])

    assert prompt == baseline
    assert SUPPRESSION_HEADER not in prompt
    assert NEVER_FABRICATE_HOOK in prompt
    assert NEVER_FABRICATE_FAILURE in prompt
    assert FINAL_CHECK in prompt


def test_run_suppression_coexists_with_restrictive_allowed_claims(monkeypatch) -> None:
    """The two instruction sets are independent and must not contradict each other: one
    governs first-person stories, the other factual/statistical claims."""
    prompt = _capture_run_prompt(
        monkeypatch,
        elicited_stories=STORIES,
        covered_sections=["Intro"],
        # A present-but-empty artifact triggers the restrictive no-claims policy.
        allowed_claims={"topic": "Topic", "claims": []},
    )

    assert _suppression_line(prompt) == f"{SUPPRESSION_HEADER} Intro"
    assert "ALLOWED CLAIMS: none available." in prompt
    assert "no specific numbers, dollar figures, percentages, or durations" in prompt
    assert NEVER_FABRICATE_HOOK in prompt
    assert NEVER_FABRICATE_FAILURE in prompt
    assert FINAL_CHECK in prompt


def test_run_suppression_precedes_the_quality_checklist(monkeypatch) -> None:
    """Position matters: the block says the rules that still apply are stated elsewhere in
    the prompt, and it must sit with the stories it refers to rather than inside the
    checklist it narrows."""
    prompt = _capture_run_prompt(monkeypatch, elicited_stories=STORIES, covered_sections=["Intro"])
    assert prompt.index("AUTHOR'S PERSONAL STORIES") < prompt.index(SUPPRESSION_HEADER)
    assert prompt.index(SUPPRESSION_HEADER) < prompt.index(NEVER_FABRICATE_HOOK)


# ---------------------------------------------------------------------------
# revise_from_user_feedback() — the post-placeholder-fill revision prompt
# ---------------------------------------------------------------------------


def test_revise_from_user_feedback_names_covered_sections(monkeypatch) -> None:
    prompt = _capture_revise_prompt(
        monkeypatch, elicited_stories=STORIES, covered_sections=["Why it broke", "Intro"]
    )
    assert _suppression_line(prompt) == f"{SUPPRESSION_HEADER} Intro, Why it broke"
    assert SUPPRESSION_INSTRUCTION in prompt
    # The block carries its own never-fabricate fallback into this prompt. The draft
    # prompt's quality checklist does not reach here (see the module docstring), so
    # asserting its clauses would pin a guarantee this path never made.
    assert "for every section not named above, the never-fabricate rules apply unchanged" in prompt
    assert "emit the placeholder for it rather than inventing one" in prompt
    assert NEVER_FABRICATE_HOOK not in prompt


def test_revise_from_user_feedback_omits_suppression_when_absent(monkeypatch) -> None:
    baseline = _capture_revise_prompt(monkeypatch, elicited_stories=STORIES)
    assert SUPPRESSION_HEADER not in baseline
    # And an empty list is the same no-op as omitting the argument entirely.
    assert _capture_revise_prompt(monkeypatch, elicited_stories=STORIES, covered_sections=[]) == (
        baseline
    )


def test_revise_from_user_feedback_omits_suppression_without_stories(monkeypatch) -> None:
    prompt = _capture_revise_prompt(monkeypatch, covered_sections=["Intro"])
    assert SUPPRESSION_HEADER not in prompt
