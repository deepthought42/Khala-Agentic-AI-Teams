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

from typing import TYPE_CHECKING

from .conftest import make_writer_agent

if TYPE_CHECKING:
    from agents.blogging.blog_writer_agent.models import WriterInput

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
# The draft prompt's own stories heading, in full. The bare phrase "AUTHOR'S PERSONAL
# STORIES" also occurs inside the suppression block and the checklist, so ordering
# assertions match this longer form to pin the heading itself.
STORIES_SECTION_HEADING = "AUTHOR'S PERSONAL STORIES (use these in the relevant sections"
SUPPRESSION_INSTRUCTION = "do not emit an [Author: ...] placeholder for those sections"


def _writer_input(**overrides) -> "WriterInput":
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
    line = next((line for line in text.splitlines() if line.startswith(SUPPRESSION_HEADER)), None)
    # Guarded rather than a bare next(): if the block vanishes entirely, the failure
    # should name the missing header and show the text, not read "StopIteration".
    assert line is not None, f"no {SUPPRESSION_HEADER!r} line found in:\n{text}"
    return line


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


def test_render_collapses_internal_whitespace_in_titles() -> None:
    """A title carrying an embedded newline must not split the single-line header.

    Titles come from parsed planning output, so a stray newline is possible; left
    alone it would push every title after it into the block's body text, where the
    model no longer reads them as covered sections.
    """
    from agents.blogging.blog_writer_agent.agent import _render_covered_sections_section

    out = _render_covered_sections_section(["Why it\nbroke", "Intro"], STORIES)
    assert _suppression_line(out) == f"{SUPPRESSION_HEADER} Intro, Why it broke"
    # ...and collapsing happens before de-duplication, so whitespace variants merge.
    merged = _render_covered_sections_section(["Why it\nbroke", "Why it  broke"], STORIES)
    assert _suppression_line(merged) == f"{SUPPRESSION_HEADER} Why it broke"


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


def test_run_prompt_is_byte_identical_when_no_entry_is_usable(monkeypatch) -> None:
    """The third omission case, and the one a reader is least likely to predict: a
    present, non-empty ``covered_sections`` whose every entry is unusable renders
    nothing, exactly as ``None`` and ``[]`` do."""
    baseline = _capture_run_prompt(monkeypatch, elicited_stories=STORIES)
    all_unusable = _capture_run_prompt(
        monkeypatch, elicited_stories=STORIES, covered_sections=["", "   ", "\n"]
    )
    assert all_unusable == baseline


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
    # Presence first, ordering second: a regression that drops either landmark should
    # name the missing one, not surface as "ValueError: substring not found".
    _suppression_line(prompt)
    assert NEVER_FABRICATE_HOOK in prompt, f"checklist hook missing from:\n{prompt}"
    # The stories heading is guarded too, and matched in its full form: the phrase
    # "AUTHOR'S PERSONAL STORIES" also appears inside the suppression block, so a bare
    # index() on it could silently measure the wrong occurrence if the real heading went
    # missing — passing or failing for a reason that has nothing to do with ordering.
    assert STORIES_SECTION_HEADING in prompt, f"stories heading missing from:\n{prompt}"
    assert prompt.index(STORIES_SECTION_HEADING) < prompt.index(SUPPRESSION_HEADER)
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


def test_revise_from_user_feedback_prompt_is_byte_identical_when_no_entry_is_usable(
    monkeypatch,
) -> None:
    """The third omission case on this builder too, matching the ``run()``-level pin: a
    present, non-empty ``covered_sections`` whose every entry is unusable renders
    nothing. Both contracts now enumerate it, so both are asserted."""
    baseline = _capture_revise_prompt(monkeypatch, elicited_stories=STORIES)
    all_unusable = _capture_revise_prompt(
        monkeypatch, elicited_stories=STORIES, covered_sections=["", "   ", "\n"]
    )

    assert all_unusable == baseline


def test_revise_from_user_feedback_omits_suppression_without_stories(monkeypatch) -> None:
    """Byte-identity, not just an absent header: the suite's stated standard for every
    no-op case, and the only assertion that also catches the block's instruction or
    fallback clauses leaking in without their header line."""
    baseline = _capture_revise_prompt(monkeypatch)
    prompt = _capture_revise_prompt(monkeypatch, covered_sections=["Intro"])

    assert prompt == baseline
    assert SUPPRESSION_HEADER not in prompt


# ---------------------------------------------------------------------------
# build_revise_all_items_prompt() — the copy-edit / gates batch-revise prompt
# ---------------------------------------------------------------------------


def _capture_batch_revise_prompt(**overrides) -> str:
    """Build the batch-revise prompt directly, with any ``ReviseWriterInput`` override."""
    from agents.blogging.blog_copy_editor_agent.models import FeedbackItem
    from agents.blogging.blog_writer_agent.models import ReviseWriterInput
    from agents.blogging.blog_writer_agent.revision import build_revise_all_items_prompt
    from agents.blogging.shared.content_plan import ContentPlanSection

    from ._content_plan_test_utils import make_content_plan

    items = [
        FeedbackItem(category="style", severity="must_fix", issue="Tighten.", suggestion="Cut.")
    ]
    kwargs = {
        "draft": "# Draft\n\nBody.",
        "feedback_items": items,
        "content_plan": make_content_plan(
            overarching_topic="Topic",
            narrative_flow="flow",
            sections=[ContentPlanSection(title="Intro", coverage_description="hook", order=0)],
        ),
    }
    kwargs.update(overrides)
    # ``draft`` and ``feedback_items`` are re-read from kwargs after the update: passing
    # ``items`` directly would let an override of ``feedback_items`` build the prompt from
    # one list and the model from another. The plan *text* stays a literal — it is a
    # separate argument from the ``content_plan`` model, so overriding ``content_plan``
    # is NOT consistency-safe here and no test does it.
    return build_revise_all_items_prompt(
        kwargs["draft"],
        kwargs["feedback_items"],
        "plan text",
        ReviseWriterInput(**kwargs),
        llm=None,
    )


def test_batch_revise_prompt_names_covered_sections() -> None:
    """The copy-edit and gates rewrite loops run *after* the story fill, so this prompt
    needs the block too: without it the stories are present but nothing says which
    sections they satisfy, and the system prompt still asks for [Author: ...]."""
    prompt = _capture_batch_revise_prompt(
        elicited_stories=STORIES, covered_sections=["Why it broke", "Intro"]
    )
    assert _suppression_line(prompt) == f"{SUPPRESSION_HEADER} Intro, Why it broke"
    assert SUPPRESSION_INSTRUCTION in prompt


def test_batch_revise_prompt_omits_suppression_when_absent() -> None:
    """Stories without ``covered_sections`` leave the prompt untouched. Absence of the
    header is pinned directly — that is what would catch a renderer emitting the block
    unconditionally — and the empty-list case by byte-identity against the same baseline."""
    baseline = _capture_batch_revise_prompt(elicited_stories=STORIES)
    assert SUPPRESSION_HEADER not in baseline
    assert _capture_batch_revise_prompt(elicited_stories=STORIES, covered_sections=[]) == baseline


def test_batch_revise_prompt_omits_suppression_without_stories() -> None:
    """The same safety gate as the other two prompts, pinned by byte-identity."""
    baseline = _capture_batch_revise_prompt()
    assert _capture_batch_revise_prompt(covered_sections=["Intro"]) == baseline


# ---------------------------------------------------------------------------
# _self_review — the rewrite that runs inside run(), after generation
# ---------------------------------------------------------------------------
#
# The suppression block reaching the generation prompt is not enough on its own.
# ``run()`` calls ``_self_review`` before returning, and both of its LLM steps rewrite
# under ``WRITING_SYSTEM_PROMPT``, whose standing rule is to substitute an
# ``[Author: ...]`` placeholder wherever no story was supplied. Worse, the checker is
# asked to flag first-person narrative "not from the AUTHOR'S PERSONAL STORIES section"
# while historically receiving only the draft — so every genuine story read as
# fabricated. A draft written from real author material could therefore have that
# material rewritten back into the placeholder the draft prompt had just suppressed,
# inside a single ``run()`` call, before anything downstream ever saw it.


STORIES_HEADING = "AUTHOR'S PERSONAL STORIES:"


def _render_context(**kwargs) -> str:
    from agents.blogging.blog_writer_agent.agent import (
        _render_covered_sections_section,
        _render_self_review_stories_context,
    )

    stories = kwargs.get("elicited_stories")
    return _render_self_review_stories_context(
        stories, _render_covered_sections_section(kwargs.get("covered_sections"), stories)
    )


def test_render_self_review_context_pairs_stories_with_the_suppression_block() -> None:
    """Both halves travel together: the checker needs the stories to judge what was
    supplied, the fixer needs the coverage to know which sections are already answered."""
    out = _render_context(elicited_stories=STORIES, covered_sections=["Why it broke", "Intro"])

    assert STORIES_HEADING in out
    assert STORIES in out
    assert _suppression_line(out) == f"{SUPPRESSION_HEADER} Intro, Why it broke"
    assert out.index(STORIES_HEADING) < out.index(SUPPRESSION_HEADER)


def test_render_self_review_context_is_empty_without_stories() -> None:
    """The same safety gate the suppression renderer applies, for the same reason: the
    block must never name a covered section in a prompt that does not carry the story."""
    assert _render_context(covered_sections=["Intro"]) == ""
    assert _render_context(elicited_stories="   ", covered_sections=["Intro"]) == ""


def test_render_self_review_context_carries_stories_without_coverage() -> None:
    """Stories alone are still worth sending: without them the checker's first rule —
    flag first-person narrative not in the stories section — misfires on every story."""
    out = _render_context(elicited_stories=STORIES)

    assert STORIES in out
    assert SUPPRESSION_HEADER not in out


def _capture_self_review_prompts(monkeypatch, *, issues: bool = False) -> list[str]:
    """Record every prompt, optionally driving self-review down its fix path.

    With ``issues=True`` the self-review checker answers with a JSON issues array, so
    ``llm_self_review`` proceeds to its rewrite and the prompt that could actually
    reintroduce a placeholder is recorded too.

    Keyed off the checker prompt's own opening rather than the call index: the
    deterministic pass fires its own rewrite before the checker whenever the generated
    draft trips one of its rules, so which call is "the checker" is not fixed.
    """
    from agents.blogging.blog_writer_agent.agent import BlogWriterAgent

    prompts: list[str] = []
    draft_envelope = '{"draft": 0}\n---DRAFT---\n# Out\nBody.'

    def fake_call(self, prompt, system_prompt=""):
        prompts.append(prompt)
        if issues and prompt.startswith("Review this draft:"):
            return '[{"issue": "Off-brand opener", "location": "Intro", "fix": "Rewrite it."}]'
        return draft_envelope

    monkeypatch.setattr(BlogWriterAgent, "_call_text", fake_call)
    return prompts


def _only_prompt_starting(prompts: list[str], prefix: str) -> str:
    """The one recorded prompt beginning with ``prefix``, or a failure naming what ran.

    Guarded and exact for the same reason ``_suppression_line`` is: a regression that
    stops a self-review step from running should say which step went missing, not index
    silently into whichever prompt happens to sit at that position.
    """
    matches = [p for p in prompts if p.startswith(prefix)]
    assert len(matches) == 1, (
        f"expected exactly one prompt starting {prefix!r}, found {len(matches)} among "
        f"{[p.splitlines()[0] for p in prompts]}"
    )
    return matches[0]


def test_run_self_review_check_prompt_carries_stories_and_coverage(monkeypatch) -> None:
    """The checker judges "was this story supplied?" — it must be handed the stories."""
    prompts = _capture_self_review_prompts(monkeypatch)
    make_writer_agent().run(
        _writer_input(elicited_stories=STORIES, covered_sections=["Why it broke", "Intro"])
    )

    check_prompt = _only_prompt_starting(prompts, "Review this draft:")
    assert STORIES in check_prompt
    assert _suppression_line(check_prompt) == f"{SUPPRESSION_HEADER} Intro, Why it broke"


def test_run_self_review_fix_prompt_carries_stories_and_coverage(monkeypatch) -> None:
    """The rewrite is the step that can actually put a placeholder back, so it needs the
    context most: it runs under the system prompt that mandates the placeholder."""
    prompts = _capture_self_review_prompts(monkeypatch, issues=True)
    make_writer_agent().run(
        _writer_input(elicited_stories=STORIES, covered_sections=["Why it broke", "Intro"])
    )

    fix_prompt = _only_prompt_starting(prompts, "Fix ONLY these issues found during self-review")
    assert STORIES in fix_prompt
    assert _suppression_line(fix_prompt) == f"{SUPPRESSION_HEADER} Intro, Why it broke"


def test_run_self_review_prompts_are_byte_identical_without_stories(monkeypatch) -> None:
    """No stories, no context — and no change to either self-review prompt."""
    baseline = _capture_self_review_prompts(monkeypatch, issues=True)
    make_writer_agent().run(_writer_input())

    with_coverage = _capture_self_review_prompts(monkeypatch, issues=True)
    make_writer_agent().run(_writer_input(covered_sections=["Intro"]))

    # Guarded, so a run that stopped reaching self-review could not make this vacuous.
    _only_prompt_starting(baseline, "Fix ONLY these issues found during self-review")
    assert with_coverage == baseline
