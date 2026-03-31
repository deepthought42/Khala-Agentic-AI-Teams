"""Tests for BlogDraftAgent.revise (plan-first batch feedback processing)."""

from __future__ import annotations

from unittest.mock import MagicMock

from blog_copy_editor_agent.models import FeedbackItem
from blog_draft_agent import BlogDraftAgent, ReviseDraftInput
from blog_draft_agent.prompts import WRITING_SYSTEM_PROMPT
from shared.content_plan import (
    ContentPlan,
    ContentPlanSection,
    RequirementsAnalysis,
    TitleCandidate,
)


def _minimal_plan() -> ContentPlan:
    return ContentPlan(
        overarching_topic="Test topic",
        narrative_flow="Intro, main, wrap.",
        sections=[
            ContentPlanSection(title="Intro", coverage_description="Hook", order=0),
        ],
        title_candidates=[TitleCandidate(title="T1", probability_of_success=0.5)],
        requirements_analysis=RequirementsAnalysis(
            plan_acceptable=True,
            scope_feasible=True,
            research_gaps=[],
        ),
    )


def test_revise_generates_plan_then_applies_all_feedback() -> None:
    llm = MagicMock()
    # Step 1 (plan) now uses complete_json; step 2 (apply) uses complete
    llm.complete_json.return_value = {
        "summary": "Fix opening hook and tighten section two.",
        "changes": [
            {"section": "intro", "feedback_ids": [1], "action": "rewrite", "rationale": "Weak opening"},
            {"section": "section two", "feedback_ids": [2], "action": "rephrase", "rationale": "Dragging"},
        ],
        "risks": [],
    }
    llm.complete.return_value = '{"draft": 0}\n---DRAFT---\n# Revised title\n\nBody here.\n'
    agent = BlogDraftAgent(
        llm_client=llm,
        writing_style_guide_content="Use short paragraphs.",
        brand_spec_content="Brand voice: practical and direct.",
    )
    items = [
        FeedbackItem(
            category="style",
            severity="must_fix",
            location="intro",
            issue="Opening is weak.",
            suggestion="Add a concrete hook.",
        ),
        FeedbackItem(
            category="structure",
            severity="should_fix",
            issue="Section two drags.",
            suggestion="Tighten examples.",
        ),
    ]
    inp = ReviseDraftInput(
        draft="# Original\n\nOld body.\n",
        feedback_items=items,
        content_plan=_minimal_plan(),
    )
    out = agent.revise(inp)

    # Step 1: complete_json for structured revision plan
    assert llm.complete_json.call_count == 1
    plan_prompt = llm.complete_json.call_args[0][0]
    assert "create a structured revision plan for this draft" in plan_prompt
    assert "Opening is weak." in plan_prompt
    assert "Section two drags." in plan_prompt
    assert llm.complete_json.call_args.kwargs.get("system_prompt") == WRITING_SYSTEM_PROMPT
    assert llm.complete_json.call_args.kwargs.get("temperature") == 0.1

    # Step 2: complete for applying the revision
    assert llm.complete.call_count == 1
    apply_prompt = llm.complete.call_args[0][0]
    assert "REVISION PLAN (execute this plan before writing):" in apply_prompt
    assert "COPY EDITOR FEEDBACK (apply every numbered item below):" in apply_prompt
    assert "Section two drags." in apply_prompt
    assert llm.complete.call_args.kwargs.get("system_prompt") == WRITING_SYSTEM_PROMPT
    assert llm.complete.call_args.kwargs.get("temperature") == 0.2

    assert "# Revised title" in out.draft
    assert "Body here." in out.draft
