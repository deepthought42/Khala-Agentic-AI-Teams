"""Tests for Winning Posts Bank exemplar injection into ContentConceptAgent."""

from __future__ import annotations

from social_media_marketing_team.agents import (
    ContentConceptAgent,
    _format_exemplar_prefix,
)
from social_media_marketing_team.models import CampaignProposal, Platform
from social_media_marketing_team.tests.conftest import make_goals


def _proposal() -> CampaignProposal:
    return CampaignProposal(
        campaign_name="Q2 growth sprint",
        objective="Drive qualified inbound",
        audience_hypothesis="Founders struggle with seed-stage GTM",
        messaging_pillars=["Pricing", "Traction"],
        channel_mix_strategy={Platform.LINKEDIN: "lead-gen"},
    )


def test_format_prefix_empty_returns_empty_string():
    assert _format_exemplar_prefix(None) == ""
    assert _format_exemplar_prefix([]) == ""


def test_format_prefix_renders_blocks():
    prefix = _format_exemplar_prefix(
        [
            {
                "platform": "linkedin",
                "engagement_score": 0.84,
                "title": "Why seed rounds fail",
                "body": "Founders skip...",
            }
        ]
    )
    assert "Prior winners (reference, do not copy):" in prefix
    assert "[Winning post on linkedin — engagement 0.84]" in prefix
    assert "Why seed rounds fail" in prefix
    assert prefix.endswith("\n\n")


def test_generate_candidates_injects_exemplars_into_concept():
    agent = ContentConceptAgent("Brand Storytelling Lead")
    goals = make_goals()
    proposal = _proposal()
    exemplars = [
        {
            "platform": "linkedin",
            "engagement_score": 0.91,
            "title": "Our $100k pricing mistake",
            "body": "We almost lost 40% of customers...",
        }
    ]

    ideas = agent.generate_candidates(proposal, goals, exemplars=exemplars)
    assert ideas, "Expected at least one generated idea"
    for idea in ideas:
        assert "[Winning post on linkedin — engagement 0.91]" in idea.concept
        assert "Our $100k pricing mistake" in idea.concept
        assert idea.concept.startswith("Prior winners (reference, do not copy):")


def test_generate_candidates_without_exemplars_matches_legacy_output():
    """Regression guard: exemplars=None must leave concept strings unchanged."""
    agent = ContentConceptAgent("Brand Storytelling Lead")
    goals = make_goals()
    proposal = _proposal()

    ideas_none = agent.generate_candidates(proposal, goals)
    ideas_empty = agent.generate_candidates(proposal, goals, exemplars=[])

    for idea in ideas_none:
        assert "[Winning post on" not in idea.concept
        assert "Prior winners" not in idea.concept

    assert [i.concept for i in ideas_none] == [i.concept for i in ideas_empty]


def test_generate_candidates_preserves_scoring_with_exemplars():
    agent = ContentConceptAgent("Brand Storytelling Lead")
    goals = make_goals()
    proposal = _proposal()

    without = agent.generate_candidates(proposal, goals)
    with_ex = agent.generate_candidates(
        proposal,
        goals,
        exemplars=[{"platform": "x", "engagement_score": 0.5, "title": "t", "body": "b"}],
    )

    assert len(without) == len(with_ex)
    for a, b in zip(without, with_ex):
        assert a.brand_fit_score == b.brand_fit_score
        assert a.audience_resonance_score == b.audience_resonance_score
        assert a.goal_alignment_score == b.goal_alignment_score
