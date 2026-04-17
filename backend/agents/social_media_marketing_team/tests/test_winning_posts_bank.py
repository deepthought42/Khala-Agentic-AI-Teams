"""Tests for the winning posts bank module.

These tests exercise the engagement score computation and the public API
functions using mock Postgres connections. They do NOT require a live
Postgres instance — ``get_conn`` is monkeypatched throughout.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from social_media_marketing_team.shared.winning_posts_bank import (
    _compute_engagement_score,
    _llm_rerank,
    find_relevant_winners,
    save_post,
)

# ---------------------------------------------------------------------------
# _compute_engagement_score
# ---------------------------------------------------------------------------


class TestComputeEngagementScore:
    def test_engagement_rate_used_directly(self):
        assert _compute_engagement_score({"engagement_rate": 0.85}) == 0.85

    def test_engagement_rate_clamped(self):
        assert _compute_engagement_score({"engagement_rate": 1.5}) == 1.0
        assert _compute_engagement_score({"engagement_rate": -0.1}) == 0.0

    def test_engagement_score_field(self):
        assert _compute_engagement_score({"engagement_score": 0.72}) == 0.72

    def test_computed_from_likes_views(self):
        score = _compute_engagement_score({"likes": 50, "comments": 10, "shares": 5, "views": 1000})
        assert abs(score - 0.065) < 0.001

    def test_engagement_fallback(self):
        assert _compute_engagement_score({"engagement": 0.6}) == 0.6

    def test_empty_metrics_returns_zero(self):
        assert _compute_engagement_score({}) == 0.0

    def test_unknown_keys_returns_zero(self):
        assert _compute_engagement_score({"impressions": 5000}) == 0.0

    def test_priority_engagement_rate_over_score(self):
        score = _compute_engagement_score({"engagement_rate": 0.9, "engagement_score": 0.5})
        assert score == 0.9

    def test_zero_views_no_crash(self):
        assert _compute_engagement_score({"likes": 10, "views": 0}) == 0.0


# ---------------------------------------------------------------------------
# save_post
# ---------------------------------------------------------------------------


class TestSavePost:
    @patch("social_media_marketing_team.shared.winning_posts_bank.get_conn")
    def test_save_returns_id(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        post_id = save_post(
            brand_id="brand1",
            campaign_name="Spring Campaign",
            platform="linkedin",
            archetype="Customer story",
            concept_title="Test concept",
            engagement_metrics={"engagement_rate": 0.85},
        )
        assert isinstance(post_id, str)
        assert len(post_id) == 12
        mock_cur.execute.assert_called_once()

    @patch("social_media_marketing_team.shared.winning_posts_bank.get_conn")
    def test_semantic_summary_generated(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_llm = MagicMock()
        mock_llm.complete.return_value = "A post about customer onboarding challenges."

        save_post(
            brand_id="brand1",
            campaign_name="Test",
            platform="linkedin",
            concept_text="Detailed concept text here",
            engagement_metrics={"engagement_rate": 0.8},
            llm_client=mock_llm,
        )
        mock_llm.complete.assert_called_once()
        call_args = mock_cur.execute.call_args[0][1]
        assert call_args[11] == "A post about customer onboarding challenges."

    @patch("social_media_marketing_team.shared.winning_posts_bank.get_conn")
    def test_semantic_summary_failure_nonfatal(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_llm = MagicMock()
        mock_llm.complete.side_effect = RuntimeError("LLM unavailable")

        post_id = save_post(
            brand_id="brand1",
            campaign_name="Test",
            platform="linkedin",
            concept_text="Concept text",
            engagement_metrics={"engagement_rate": 0.8},
            llm_client=mock_llm,
        )
        assert isinstance(post_id, str)
        call_args = mock_cur.execute.call_args[0][1]
        assert call_args[11] == ""


# ---------------------------------------------------------------------------
# find_relevant_winners & _keyword_scored_candidates
# ---------------------------------------------------------------------------


def _make_row(
    post_id: str,
    brand_id: str = "brand1",
    platform: str = "linkedin",
    keywords: list | None = None,
    engagement_score: float = 0.8,
    semantic_summary: str = "",
    created_at: datetime | None = None,
    **overrides,
) -> dict:
    now = created_at or datetime.now(timezone.utc)
    return {
        "id": post_id,
        "brand_id": brand_id,
        "campaign_name": "Campaign",
        "platform": platform,
        "archetype": overrides.get("archetype", ""),
        "concept_title": overrides.get("concept_title", f"Concept {post_id}"),
        "concept_text": "",
        "post_copy": "",
        "content_format": "carousel",
        "cta_variant": "",
        "keywords": keywords or [],
        "semantic_summary": semantic_summary,
        "engagement_metrics": {},
        "engagement_score": engagement_score,
        "posted_at": now,
        "source_job_id": "",
        "created_at": now,
    }


class TestFindRelevantWinners:
    def test_empty_keywords_returns_empty(self):
        assert find_relevant_winners("brand1", []) == []

    @patch("social_media_marketing_team.shared.winning_posts_bank.get_conn")
    def test_keyword_overlap_ranking(self, mock_get_conn):
        rows = [
            _make_row("p1", keywords=["engagement", "growth", "leads"]),
            _make_row("p2", keywords=["engagement"]),
            _make_row("p3", keywords=["growth", "engagement"]),
        ]
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = rows
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        results = find_relevant_winners(
            "brand1",
            ["engagement", "growth"],
            limit=3,
        )
        assert len(results) >= 2
        assert results[0]["id"] in ("p1", "p3")

    @patch("social_media_marketing_team.shared.winning_posts_bank.get_conn")
    def test_winner_threshold_passed_to_sql(self, mock_get_conn):
        """Verify that the min_score threshold is passed to the SQL query params."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = []
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        find_relevant_winners("brand1", ["engagement"], min_score=0.9)
        sql_args = mock_cur.execute.call_args[0][1]
        assert sql_args[1] == 0.9

    def test_no_keyword_overlap_returns_empty(self):
        """Posts with no keyword overlap are filtered out in Python."""
        from social_media_marketing_team.shared.winning_posts_bank import _keyword_scored_candidates

        with patch("social_media_marketing_team.shared.winning_posts_bank.get_conn") as mock_gc:
            rows = [_make_row("p1", keywords=["unrelated"], engagement_score=0.9)]
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_cur.fetchall.return_value = rows
            mock_gc.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

            results = _keyword_scored_candidates("brand1", ["engagement", "growth"])
            assert len(results) == 0


class TestLlmRerank:
    def test_rerank_reorders_candidates(self):
        candidates = [
            {
                "platform": "linkedin",
                "engagement_score": 0.8,
                "semantic_summary": "Post about growth",
            },
            {
                "platform": "linkedin",
                "engagement_score": 0.9,
                "semantic_summary": "Post about engagement",
            },
            {"platform": "x", "engagement_score": 0.75, "semantic_summary": "Post about leads"},
        ]
        mock_llm = MagicMock()
        mock_llm.complete_json.return_value = [2, 1, 3]

        result = _llm_rerank(candidates, "Increase engagement", mock_llm, limit=2)
        assert len(result) == 2
        assert result[0]["semantic_summary"] == "Post about engagement"
        assert result[1]["semantic_summary"] == "Post about growth"

    def test_rerank_fallback_on_error(self):
        candidates = [
            {"platform": "linkedin", "engagement_score": 0.8, "semantic_summary": "Post A"},
        ]
        mock_llm = MagicMock()
        mock_llm.complete_json.side_effect = RuntimeError("LLM error")

        result = _llm_rerank(candidates, "Something", mock_llm, limit=1)
        assert result == []


# ---------------------------------------------------------------------------
# Exemplar integration in ContentConceptAgent
# ---------------------------------------------------------------------------


class TestConceptAgentWithWinners:
    def test_generate_with_winners_boosts_probability(self):
        from social_media_marketing_team.agents import ContentConceptAgent
        from social_media_marketing_team.models import BrandGoals, CampaignProposal

        agent = ContentConceptAgent("Brand Storytelling Lead")
        goals = BrandGoals(
            brand_name="Acme",
            target_audience="SaaS founders",
            goals=["engagement"],
        )
        proposal = CampaignProposal(
            campaign_name="Test",
            objective="engagement growth",
            audience_hypothesis="SaaS founders face pain with growth.",
            messaging_pillars=["Practical education"],
        )

        winners = [
            {
                "id": "w1",
                "archetype": "Customer story",
                "concept_title": "Practical education – Customer story",
                "engagement_score": 0.88,
                "platform": "linkedin",
            }
        ]

        ideas_with = agent.generate_candidates(proposal, goals, winners=winners)
        ideas_without = agent.generate_candidates(proposal, goals, winners=None)

        story_with = [i for i in ideas_with if "Customer story" in i.title]
        story_without = [i for i in ideas_without if "Customer story" in i.title]

        assert story_with and story_without
        assert (
            story_with[0].estimated_engagement_probability
            >= story_without[0].estimated_engagement_probability
        )
        assert story_with[0].exemplar_source_ids == ["w1"]
        assert "inspired by" in story_with[0].primary_hook

    def test_generate_without_winners_matches_baseline(self):
        from social_media_marketing_team.agents import ContentConceptAgent
        from social_media_marketing_team.models import BrandGoals, CampaignProposal

        agent = ContentConceptAgent("Brand Storytelling Lead")
        goals = BrandGoals(
            brand_name="Acme",
            target_audience="SaaS founders",
            goals=["engagement"],
        )
        proposal = CampaignProposal(
            campaign_name="Test",
            objective="engagement growth",
            audience_hypothesis="SaaS founders struggle with growth.",
            messaging_pillars=["Practical education"],
        )

        ideas_none = agent.generate_candidates(proposal, goals, winners=None)
        ideas_empty = agent.generate_candidates(proposal, goals, winners=[])
        assert len(ideas_none) == len(ideas_empty)
        for a, b in zip(ideas_none, ideas_empty):
            assert a.estimated_engagement_probability == b.estimated_engagement_probability
            assert a.exemplar_source_ids == []


# ---------------------------------------------------------------------------
# Orchestrator brand_id pass-through
# ---------------------------------------------------------------------------


class TestOrchestratorBrandId:
    def test_run_passes_brand_id_and_reports_winners(self):
        from social_media_marketing_team.models import HumanReview
        from social_media_marketing_team.orchestrator import SocialMediaMarketingOrchestrator

        from .conftest import make_goals

        orch = SocialMediaMarketingOrchestrator()
        result = orch.run(
            goals=make_goals(),
            human_review=HumanReview(approved=True),
            brand_id="test-brand",
        )
        assert result.status.value == "approved_for_testing"
        assert result.winners_retrieved == 0

    def test_run_without_brand_id_still_works(self):
        from social_media_marketing_team.models import HumanReview
        from social_media_marketing_team.orchestrator import SocialMediaMarketingOrchestrator

        from .conftest import make_goals

        orch = SocialMediaMarketingOrchestrator()
        result = orch.run(
            goals=make_goals(),
            human_review=HumanReview(approved=True),
        )
        assert result.status.value == "approved_for_testing"
        assert result.winners_retrieved == 0
        assert result.content_plan is not None
