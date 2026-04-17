"""Helpers for persisting social media post performance observations.

Extracted from ``api/main.py`` so tests can exercise the logic without
importing the full FastAPI app (which pulls in apscheduler, strands,
and the blog_research_agent tree).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def extract_brand_id(job: dict) -> str:
    """Return the ``brand_id`` stored on the job, or ``""`` if absent."""
    payload = job.get("request_payload")
    if isinstance(payload, dict):
        return payload.get("brand_id", "")
    return ""


def extract_campaign_name(job: dict) -> str | None:
    """Return the campaign name from the completed job result, if any."""
    result = job.get("result")
    if isinstance(result, dict):
        proposal = result.get("proposal")
        if isinstance(proposal, dict):
            return proposal.get("campaign_name")
    return None


def find_concept_meta(result: dict, concept_title: str) -> dict:
    """Walk the job result to find metadata for a concept by title.

    Keywords for the winners bank combine the concept's ``linked_goals``
    with its messaging pillar (parsed from the title prefix before
    " \u2013 " / " - "). This matches the retrieval query, which uses
    ``proposal.messaging_pillars + goals.goals`` \u2014 storing only
    ``linked_goals`` would cause pillar-based lookups to miss.
    """
    content_plan = result.get("content_plan")
    if not isinstance(content_plan, dict):
        return {}
    for idea in content_plan.get("approved_ideas", []):
        if not isinstance(idea, dict):
            continue
        if idea.get("title") == concept_title:
            title = idea.get("title", "")
            pillar = ""
            archetype = ""
            if " \u2013 " in title:
                pillar, archetype = title.split(" \u2013 ", 1)
            elif " - " in title:
                pillar, archetype = title.split(" - ", 1)
            keywords = list(idea.get("linked_goals") or [])
            if pillar and pillar not in keywords:
                keywords.append(pillar)
            return {
                "archetype": archetype,
                "concept": idea.get("concept", ""),
                "content_format": idea.get("content_format", ""),
                "cta_variant": idea.get("cta_variant", ""),
                "keywords": keywords,
            }
    return {}


def persist_observations_to_bank(job: dict, job_id: str, observations: list) -> int:
    """Persist post observations to the winning posts bank.

    No-op when Postgres is not configured or no ``brand_id`` is on the job.
    Each observation failure is logged and skipped so a single bad row
    cannot poison the whole batch. Returns the count persisted.
    """
    from shared_postgres import is_postgres_enabled

    if not is_postgres_enabled():
        return 0

    from .winning_posts_bank import save_post

    brand_id = extract_brand_id(job)
    if not brand_id:
        return 0

    result = job.get("result") or {}
    persisted = 0
    for obs in observations:
        obs_dict = obs.model_dump() if hasattr(obs, "model_dump") else obs
        concept_title = obs_dict.get("concept_title", "")
        concept_meta = find_concept_meta(result, concept_title)
        raw_metrics: Any = obs_dict.get("metrics")
        metrics = (
            {m["name"]: m["value"] for m in raw_metrics} if isinstance(raw_metrics, list) else {}
        )
        try:
            save_post(
                brand_id=brand_id,
                campaign_name=obs_dict.get("campaign_name", ""),
                platform=obs_dict.get("platform", ""),
                archetype=concept_meta.get("archetype", ""),
                concept_title=concept_title,
                concept_text=concept_meta.get("concept", ""),
                post_copy="",
                content_format=concept_meta.get("content_format", ""),
                cta_variant=concept_meta.get("cta_variant", ""),
                keywords=concept_meta.get("keywords", []),
                engagement_metrics=metrics,
                posted_at=obs_dict.get("posted_at"),
                source_job_id=job_id,
            )
            persisted += 1
        except Exception:
            logger.warning("Failed to persist observation to winning posts bank", exc_info=True)
    return persisted
