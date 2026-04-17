"""Postgres-backed winning posts bank for the social media marketing team.

Stores post observations with engagement metrics so that high-performing
content can be retrieved and injected as few-shot exemplars into future
concept generation. Modelled on ``blogging/shared/story_bank.py``.

Storage: the ``social_media_posts`` table declared in
``social_media_marketing_team.postgres`` and registered from the team's
FastAPI lifespan.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from psycopg.rows import dict_row

from shared_postgres import Json, get_conn
from shared_postgres.metrics import timed_query

logger = logging.getLogger(__name__)

_STORE = "social_media_winning_posts"

WINNER_THRESHOLD = 0.7
DEFAULT_LOOKBACK_DAYS = 90


def _row_ts(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "brand_id": row["brand_id"],
        "campaign_name": row["campaign_name"],
        "platform": row["platform"],
        "archetype": row["archetype"],
        "concept_title": row["concept_title"],
        "concept_text": row["concept_text"],
        "post_copy": row["post_copy"],
        "content_format": row["content_format"],
        "cta_variant": row["cta_variant"],
        "keywords": list(row["keywords"] or []),
        "semantic_summary": row["semantic_summary"] or "",
        "engagement_metrics": dict(row["engagement_metrics"] or {}),
        "engagement_score": float(row["engagement_score"] or 0.0),
        "posted_at": _row_ts(row.get("posted_at")),
        "source_job_id": row.get("source_job_id") or "",
        "created_at": _row_ts(row["created_at"]),
    }


def _compute_engagement_score(metrics: dict) -> float:
    """Compute a 0-1 composite from raw metric values.

    Priority: engagement_rate > engagement_score > likes+comments+shares/views > engagement.
    """
    if "engagement_rate" in metrics:
        val = float(metrics["engagement_rate"])
        return max(0.0, min(1.0, val))

    if "engagement_score" in metrics:
        val = float(metrics["engagement_score"])
        return max(0.0, min(1.0, val))

    likes = float(metrics.get("likes", 0))
    comments = float(metrics.get("comments", 0))
    shares = float(metrics.get("shares", 0))
    views = float(metrics.get("views", 0))
    if views > 0 and (likes + comments + shares) > 0:
        return max(0.0, min(1.0, (likes + comments + shares) / views))

    if "engagement" in metrics:
        val = float(metrics["engagement"])
        return max(0.0, min(1.0, val))

    return 0.0


@timed_query(store=_STORE, op="save_post")
def save_post(
    brand_id: str,
    campaign_name: str,
    platform: str,
    archetype: str = "",
    concept_title: str = "",
    concept_text: str = "",
    post_copy: str = "",
    content_format: str = "",
    cta_variant: str = "",
    keywords: Optional[list[str]] = None,
    engagement_metrics: Optional[dict] = None,
    posted_at: Optional[str] = None,
    source_job_id: Optional[str] = None,
    llm_client: Any = None,
) -> str:
    """Persist a post observation and return its ID."""
    post_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc)
    metrics = engagement_metrics or {}
    score = _compute_engagement_score(metrics)

    summary = ""
    if llm_client is not None and concept_text:
        try:
            summary = (
                llm_client.complete(
                    f"Summarize this social media post concept in one sentence:\n\n{concept_text}",
                    system_prompt="Write a single sentence summary. No preamble, no quotes.",
                )
                or ""
            ).strip()
        except Exception as e:
            logger.warning("Winning posts bank: summary generation failed (non-fatal): %s", e)

    parsed_posted_at = None
    if posted_at:
        try:
            parsed_posted_at = datetime.fromisoformat(posted_at)
        except (ValueError, TypeError):
            pass

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO social_media_posts "
            "(id, brand_id, campaign_name, platform, archetype, concept_title, "
            "concept_text, post_copy, content_format, cta_variant, keywords, "
            "semantic_summary, engagement_metrics, engagement_score, posted_at, "
            "source_job_id, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                post_id,
                brand_id,
                campaign_name,
                platform,
                archetype,
                concept_title,
                concept_text,
                post_copy,
                content_format,
                cta_variant,
                Json(keywords or []),
                summary,
                Json(metrics),
                score,
                parsed_posted_at,
                source_job_id,
                now,
            ),
        )

    logger.info(
        "Winning posts bank: saved post %s (brand=%s, platform=%s, score=%.2f, has_summary=%s)",
        post_id,
        brand_id,
        platform,
        score,
        bool(summary),
    )
    return post_id


@timed_query(store=_STORE, op="find_relevant_winners")
def find_relevant_winners(
    brand_id: str,
    query_keywords: list[str],
    platform: Optional[str] = None,
    limit: int = 5,
    concept_opportunity: Optional[str] = None,
    min_score: float = WINNER_THRESHOLD,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    llm_client: Any = None,
) -> list[dict[str, Any]]:
    """Two-stage retrieval: keyword overlap then optional LLM rerank."""
    if not query_keywords:
        return []

    candidates = _keyword_scored_candidates(
        brand_id,
        query_keywords,
        platform=platform,
        min_score=min_score,
        lookback_days=lookback_days,
        limit=max(limit, 10),
    )
    if not candidates:
        return []

    candidates_with_summaries = [c for c in candidates if c.get("semantic_summary")]
    if concept_opportunity and llm_client and len(candidates_with_summaries) > limit:
        reranked = _llm_rerank(candidates_with_summaries, concept_opportunity, llm_client, limit)
        if reranked:
            return reranked

    return candidates[:limit]


def _keyword_scored_candidates(
    brand_id: str,
    query_keywords: list[str],
    platform: Optional[str] = None,
    min_score: float = WINNER_THRESHOLD,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    limit: int = 10,
) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    sql = (
        "SELECT id, brand_id, campaign_name, platform, archetype, concept_title, "
        "concept_text, post_copy, content_format, cta_variant, keywords, "
        "semantic_summary, engagement_metrics, engagement_score, posted_at, "
        "source_job_id, created_at "
        "FROM social_media_posts "
        "WHERE brand_id = %s AND engagement_score >= %s AND created_at >= %s"
    )
    params: list[Any] = [brand_id, min_score, cutoff]

    if platform:
        sql += " AND platform = %s"
        params.append(platform)

    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    query_lower = {k.lower().strip() for k in query_keywords if k.strip()}
    if not query_lower:
        return []

    scored: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        post_kw = {str(k).lower().strip() for k in (row["keywords"] or [])}
        overlap = len(query_lower & post_kw)
        if overlap > 0:
            scored.append((overlap, _row_to_dict(row)))

    scored.sort(key=lambda t: (-t[0], -t[1]["engagement_score"]))
    return [item for _, item in scored[:limit]]


def _llm_rerank(
    candidates: list[dict[str, Any]],
    concept_opportunity: str,
    llm_client: Any,
    limit: int,
) -> list[dict[str, Any]]:
    summaries = "\n".join(
        f"{i + 1}. [{c['platform']}, score={c['engagement_score']:.2f}] {c['semantic_summary']}"
        for i, c in enumerate(candidates)
    )
    prompt = (
        f"Concept needed: {concept_opportunity}\n\n"
        f"Candidate winning posts (by summary):\n{summaries}\n\n"
        f"Return a JSON array of the top {limit} indices (1-based) ranked by relevance "
        f"to the concept needed. Most relevant first."
    )
    try:
        data = llm_client.complete_json(
            prompt,
            system_prompt="Return a JSON array of integers only. No other text.",
        )
        indices = data if isinstance(data, list) else data.get("indices", data.get("text", []))
        if isinstance(indices, list):
            reranked: list[dict[str, Any]] = []
            for idx in indices[:limit]:
                i = int(idx) - 1
                if 0 <= i < len(candidates):
                    reranked.append(candidates[i])
            if reranked:
                return reranked
    except Exception as e:
        logger.warning(
            "Winning posts bank LLM reranking failed (falling back to keyword scoring): %s", e
        )
    return []


@timed_query(store=_STORE, op="list_posts")
def list_posts(brand_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, brand_id, campaign_name, platform, archetype, concept_title, "
            "concept_text, post_copy, content_format, cta_variant, keywords, "
            "semantic_summary, engagement_metrics, engagement_score, posted_at, "
            "source_job_id, created_at "
            "FROM social_media_posts "
            "WHERE brand_id = %s "
            "ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (brand_id, limit, offset),
        )
        return [_row_to_dict(row) for row in cur.fetchall()]


@timed_query(store=_STORE, op="get_post")
def get_post(post_id: str) -> Optional[dict[str, Any]]:
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, brand_id, campaign_name, platform, archetype, concept_title, "
            "concept_text, post_copy, content_format, cta_variant, keywords, "
            "semantic_summary, engagement_metrics, engagement_score, posted_at, "
            "source_job_id, created_at "
            "FROM social_media_posts WHERE id = %s",
            (post_id,),
        )
        row = cur.fetchone()
        return _row_to_dict(row) if row else None


@timed_query(store=_STORE, op="delete_post")
def delete_post(post_id: str) -> bool:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM social_media_posts WHERE id = %s", (post_id,))
        return cur.rowcount > 0
