"""End-to-end proof that the blogging writer and copy editor's cached
brand-spec / writing-guideline system segment actually reaches the wire,
stays stable within a run, invalidates on a guideline edit, degrades cleanly
for a non-caching client, and has genuinely left the user turn.

Scope: drives ``BlogWriterAgent`` and ``BlogCopyEditorAgent`` directly against
a real, Claude-backed ``ClaudeLLMClient`` with a fake Anthropic SDK
underneath (mirrors ``llm_service/tests/test_cache_breakpoint_e2e.py`` and
``software_engineering_team/tests/test_chunk_reviewer_cache_e2e.py``), so
every assertion reads the actual outgoing ``messages.stream(**kwargs)``
payload rather than an agent-internal attribute. The agent-attribute-level
wiring (``agent._system_prompt_content``, kwarg forwarding) already has
dedicated coverage in ``test_blog_writer_agent.py`` and
``test_blog_copy_editor_agent.py``; this module only adds what those cannot
prove: what the bytes on the wire actually look like, across calls, and
across a guideline edit.

Two things every wire-level assertion here must account for:

- Strands separates the persona and the marked segment with a bare ``"\\n"``
  system block (``strands_adapter._join_system_segments_with_newline``), so
  the real shape is ``[persona, "\\n", marked]``, not a single marked block.
- Claude's JSON-mode wire path appends an unmarked JSON-only instruction
  block after the system content (``clients.claude._json_system``).

Both mean "exactly one cache_control block" must be checked by filtering the
system content for ``cache_control``, never by asserting its length or a
fixed index.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from agents.blogging.blog_copy_editor_agent import BlogCopyEditorAgent, CopyEditorInput
from agents.blogging.blog_copy_editor_agent.prompts import COPY_EDITOR_PROMPT
from agents.blogging.blog_writer_agent import BlogWriterAgent, WriterInput
from agents.blogging.shared.content_plan import ContentPlanSection, TitleCandidate
from agents.blogging.shared.style_loader import append_guidelines, load_style_file
from strands import Agent

from llm_client_fakes import _make_claude_client, _text_message
from llm_service import CacheBreakpoint, DummyLLMClient, build_system_prompt_with_content
from llm_service.strands_adapter import LLMClientModel

from ._content_plan_test_utils import make_content_plan


def _cache_marked(system: Any) -> List[dict]:
    """Return only the system-content blocks carrying a real cache breakpoint.

    A list-form Anthropic ``system`` payload mixes marked and unmarked blocks
    (persona text, a bare ``"\\n"`` separator, a trailing JSON-only
    instruction) -- filtering, rather than indexing or counting the whole
    list, is what makes "exactly one cache_control block" a safe assertion
    regardless of which call path produced the payload.
    """
    if not isinstance(system, list):
        return []
    return [
        block
        for block in system
        if isinstance(block, dict) and block.get("cache_control") == {"type": "ephemeral"}
    ]


def _writer_input(**overrides: Any) -> WriterInput:
    plan = make_content_plan(
        overarching_topic="Topic",
        narrative_flow="flow",
        sections=[ContentPlanSection(title="Intro", coverage_description="hook", order=0)],
        title_candidates=[TitleCandidate(title="T", probability_of_success=0.5)],
    )
    kwargs: Dict[str, Any] = {"content_plan": plan, "audience": "devs", "tone_or_purpose": "inform"}
    kwargs.update(overrides)
    return WriterInput(**kwargs)


def _approving_reply(summary: str) -> str:
    return json.dumps({"approved": True, "summary": summary, "feedback_items": []})


def _no_self_review(self: Any, draft: str, *args: Any, **kwargs: Any) -> str:
    """Stub for ``BlogWriterAgent._self_review``: returns ``draft`` unchanged.

    Signature-agnostic on purpose -- ``*args``/``**kwargs`` swallow whatever
    else the real method's call site passes (currently a positional
    ``allowed_claims_section``), so a future rename or a switch to keyword
    invocation there doesn't turn this stub into an opaque ``TypeError``
    instead of a meaningful assertion failure. The tests using this stub
    only need "self-review is a no-op that returns the draft".
    """
    return draft


# ---------------------------------------------------------------------------
# Writer / copy editor wire payload each carry exactly one cache_control block
# ---------------------------------------------------------------------------


def test_writer_wire_payload_carries_single_cache_control_block(monkeypatch) -> None:
    """The writer's real outgoing wire payload carries exactly one
    ``cache_control: {"type": "ephemeral"}`` block, and that block's text
    contains the brand-spec and style-guide content -- the acceptance
    criterion asserted at the wire boundary, not at ``agent._system_prompt_content``
    (already covered by ``test_blog_writer_agent.py``)."""
    client, fake_messages = _make_claude_client(
        [_text_message('{"draft": 0}\n---DRAFT---\n# Title\n\nBody paragraph text.')]
    )
    model = LLMClientModel(client, agent_key="blogging_writer")
    agent = BlogWriterAgent(
        llm_client=model,
        writing_style_guide_content="Use concise, natural sentences.",
        brand_spec_content="Acme voice: bold and direct.",
    )
    # Self-review is a second, unrelated LLM call; disabling it keeps this
    # test to the single draft call the wire assertions below depend on.
    monkeypatch.setattr(BlogWriterAgent, "_self_review", _no_self_review)

    agent.run(_writer_input())

    assert len(fake_messages.captured_calls) == 1
    system = fake_messages.captured_calls[0]["system"]
    marked = _cache_marked(system)
    assert len(marked) == 1, f"expected exactly one cache_control block, got {system}"
    text = marked[0]["text"]
    assert "--- BRAND SPEC ---" in text
    assert "Acme voice: bold and direct." in text
    assert "--- WRITING STYLE GUIDE ---" in text
    assert "Use concise, natural sentences." in text


def test_copy_editor_wire_payload_carries_single_cache_control_block() -> None:
    """Same wire-boundary proof as the writer's, for the copy editor's single
    JSON-gated call."""
    client, fake_messages = _make_claude_client([_text_message(_approving_reply("Looks good."))])
    model = LLMClientModel(client, agent_key="blogging_copy_editor")
    editor = BlogCopyEditorAgent(
        llm_client=model,
        brand_spec_content="Acme voice: bold and direct.",
        writing_style_guide_content="Use short sentences.",
    )

    editor.run(CopyEditorInput(draft="A draft body long enough to review."))

    assert len(fake_messages.captured_calls) == 1
    system = fake_messages.captured_calls[0]["system"]
    marked = _cache_marked(system)
    assert len(marked) == 1, f"expected exactly one cache_control block, got {system}"
    text = marked[0]["text"]
    assert "--- BRAND SPEC ---" in text
    assert "Acme voice: bold and direct." in text
    assert "--- WRITING STYLE GUIDE ---" in text
    assert "Use short sentences." in text


# ---------------------------------------------------------------------------
# Stability across iterations: the one property that makes caching pay off
# ---------------------------------------------------------------------------


def test_marked_segment_byte_identical_across_two_copy_edit_iterations() -> None:
    """A cached prefix that changes between calls is worse than no caching --
    it pays the write cost every time and never reads. Two consecutive
    copy-edit iterations, reviewing genuinely different draft text, must
    still carry byte-identical marked segments; only the user turn should
    differ."""
    client, fake_messages = _make_claude_client(
        [
            _text_message(_approving_reply("First pass, needs more work.")),
            _text_message(_approving_reply("Second pass, approved.")),
        ]
    )
    model = LLMClientModel(client, agent_key="blogging_copy_editor")
    editor = BlogCopyEditorAgent(
        llm_client=model,
        brand_spec_content="Acme voice: bold and direct.",
        writing_style_guide_content="Use short sentences.",
    )

    editor.run(CopyEditorInput(draft="First draft body, quite different from the second one."))
    editor.run(
        CopyEditorInput(
            draft="Second draft body, revised after feedback, and considerably longer than the first."
        )
    )

    assert len(fake_messages.captured_calls) == 2
    system_1 = fake_messages.captured_calls[0]["system"]
    system_2 = fake_messages.captured_calls[1]["system"]
    assert system_1 == system_2, "marked segment must be byte-identical across iterations"
    assert len(_cache_marked(system_1)) == 1

    user_1 = fake_messages.captured_calls[0]["messages"][-1]["content"]
    user_2 = fake_messages.captured_calls[1]["messages"][-1]["content"]
    assert user_1 != user_2, "sanity check: the two iterations must review different drafts"


# ---------------------------------------------------------------------------
# Invalidation: a guideline edit + agent rebuild must change the segment
# ---------------------------------------------------------------------------


def test_marked_segment_rekeys_after_append_guidelines_and_rebuild(tmp_path) -> None:
    """Mirrors the pipeline's append-guidelines-then-rebuild sequence: once a
    guideline update is appended to the style guide file and the agent is
    reconstructed from the reloaded text, the cached segment reflects the
    new text. The cache must invalidate, not serve a stale prefix."""
    style_path = tmp_path / "writing_guidelines.md"
    style_path.write_text("Use short, punchy sentences.\n", encoding="utf-8")
    brand_text = "Acme voice: bold and direct."

    client, fake_messages = _make_claude_client(
        [
            _text_message(_approving_reply("Before the guideline update.")),
            _text_message(_approving_reply("After the guideline update.")),
        ]
    )
    model = LLMClientModel(client, agent_key="blogging_copy_editor")

    style_text = load_style_file(style_path, "writing style guide")
    editor = BlogCopyEditorAgent(
        llm_client=model, brand_spec_content=brand_text, writing_style_guide_content=style_text
    )
    editor.run(CopyEditorInput(draft="A draft body long enough to review."))

    assert append_guidelines(
        style_path,
        [
            {
                "category": "tone",
                "description": "No exclamation points",
                "guideline_text": "Never use exclamation points.",
            }
        ],
    )
    style_text = load_style_file(style_path, "writing style guide")
    # Rebuilt from the reloaded text, exactly as the pipeline does after an
    # append_guidelines edit -- a fresh agent instance, same backing model.
    editor = BlogCopyEditorAgent(
        llm_client=model, brand_spec_content=brand_text, writing_style_guide_content=style_text
    )
    editor.run(CopyEditorInput(draft="A draft body long enough to review."))

    assert len(fake_messages.captured_calls) == 2
    system_1 = fake_messages.captured_calls[0]["system"]
    system_2 = fake_messages.captured_calls[1]["system"]
    assert system_1 != system_2, "the segment must change after the guideline edit and rebuild"

    marked_1 = _cache_marked(system_1)
    marked_2 = _cache_marked(system_2)
    assert len(marked_1) == 1
    assert len(marked_2) == 1
    assert "Never use exclamation points." not in marked_1[0]["text"]
    assert "Never use exclamation points." in marked_2[0]["text"]


# ---------------------------------------------------------------------------
# Degradation: a non-caching client must see the marker as inert
# ---------------------------------------------------------------------------


def test_non_caching_client_flattens_cache_breakpoint_identically_to_plain_text() -> None:
    """For a backing client whose ``supports_prompt_caching()`` is ``False``
    (``DummyLLMClient``), the ``CacheBreakpoint`` marker changes nothing
    observable: the model receives exactly the text it would if the
    identical guideline content had been passed as a plain string instead of
    a ``CacheBreakpoint`` -- the documented degrade-to-plain-text contract in
    ``strands_adapter.stream``.

    The capturing client is wrapped in ``LLMClientModel`` (production's own
    wrapper around a raw ``LLMClient``) rather than passed directly as
    ``llm_client``: ``DummyLLMClient`` implements Strands' ``Model`` ABC
    itself, so an unwrapped instance would make Strands call its ``stream()``
    directly and never reach ``strands_adapter.LLMClientModel.stream``'s
    caching-vs-flatten branch at all -- the very code path this test exists
    to exercise."""

    class _SystemCapturingLLM(DummyLLMClient):
        def __init__(self) -> None:
            super().__init__()
            self.system_prompts: List[Any] = []

        def complete_json(self, prompt: str, *, system_prompt: Any = None, **kwargs: Any) -> dict:
            self.system_prompts.append(system_prompt)
            return {"approved": True, "summary": "ok", "feedback_items": []}

    raw_llm = _SystemCapturingLLM()
    model = LLMClientModel(raw_llm, agent_key="blogging_copy_editor")
    assert model.supports_prompt_caching() is False
    editor = BlogCopyEditorAgent(
        llm_client=model,
        brand_spec_content="Acme voice: bold and direct.",
        writing_style_guide_content="Use short sentences.",
    )

    editor.run(CopyEditorInput(draft="A draft body long enough to review."))

    assert len(raw_llm.system_prompts) == 1
    flattened = raw_llm.system_prompts[0]
    assert isinstance(flattened, str)
    assert "Acme voice: bold and direct." in flattened
    assert "Use short sentences." in flattened

    breakpoint_segment = editor._system_prompt_content[0]
    assert isinstance(breakpoint_segment, CacheBreakpoint)
    plain_equivalent = build_system_prompt_with_content(
        COPY_EDITOR_PROMPT, [breakpoint_segment.text]
    )
    raw_llm_control = _SystemCapturingLLM()
    model_control = LLMClientModel(raw_llm_control, agent_key="blogging_copy_editor")
    Agent(model=model_control, system_prompt=plain_equivalent)("hello")

    assert raw_llm_control.system_prompts[0] == flattened


# ---------------------------------------------------------------------------
# The guideline text has genuinely left the user turn
# ---------------------------------------------------------------------------


def test_user_turn_no_longer_carries_guideline_text(monkeypatch) -> None:
    """Regression guard for the epic's headline claim: the assembled user
    prompt no longer embeds the full brand-spec + writing-guideline text
    (``docs/brand_spec_prompt.md`` + ``docs/writing_guidelines.md``), which
    now travels only via the cached system segment, and the user prompt has
    shrunk accordingly."""
    from agents.blogging.agent_implementations.pipeline.constants import (
        BRAND_SPEC_PROMPT_PATH,
        STYLE_GUIDE_PATH,
    )

    brand_text = BRAND_SPEC_PROMPT_PATH.read_text(encoding="utf-8")
    style_text = STYLE_GUIDE_PATH.read_text(encoding="utf-8")
    combined_size = len(brand_text) + len(style_text)

    class _PromptCapturingLLM(DummyLLMClient):
        """Captures every user-turn prompt handed to the LLM client."""

        def __init__(self) -> None:
            super().__init__()
            self.all_prompts: List[str] = []

        def complete_json(self, prompt: str, **kwargs: Any) -> dict:
            self.all_prompts.append(prompt)
            # The "draft" value here is an int, not a string, so
            # extract_draft_after_marker (text_parsing.py) rejects it and
            # returns "" -- BlogWriterAgent.run then treats that as no draft
            # and substitutes its placeholder, which skips the self-review
            # call. Net effect: exactly one LLM call per run(), so
            # all_prompts below holds only this single draft (user-turn)
            # prompt. A "realistic" string draft here would take a different
            # path and change that call count, breaking the len(...) == 1
            # assertion for reasons unrelated to the cache-breakpoint
            # behavior under test.
            return {"draft": 0}

    llm = _PromptCapturingLLM()
    agent = BlogWriterAgent(
        llm_client=llm, writing_style_guide_content=style_text, brand_spec_content=brand_text
    )
    monkeypatch.setattr(BlogWriterAgent, "_self_review", _no_self_review)

    agent.run(_writer_input())

    assert len(agent._system_prompt_content) == 1
    segment_text = agent._system_prompt_content[0].text
    assert len(segment_text) >= combined_size

    assert len(llm.all_prompts) == 1
    draft_prompt = llm.all_prompts[0]

    # Literal, non-templated sentences from each real guideline file: present
    # in the cached segment, absent from the user turn.
    style_anchor = "Use these rules for every piece of content."
    brand_anchor = "Use it as a reference when generating content, communications, social posts"
    assert style_anchor in segment_text
    assert style_anchor not in draft_prompt
    assert brand_anchor in segment_text
    assert brand_anchor not in draft_prompt

    # If the ~21KB combined guideline text were still embedded in the user
    # turn (the pre-change shape), draft_prompt alone would approach or
    # exceed combined_size; the outline/instructions it actually carries are
    # a small fraction of that.
    assert len(draft_prompt) < combined_size * 0.25
