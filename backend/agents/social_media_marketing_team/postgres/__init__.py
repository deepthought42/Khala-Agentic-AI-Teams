"""Postgres schema for the social media marketing team.

Registered from the team's FastAPI lifespan via ``register_team_schemas``.
See ``backend/agents/shared_postgres/README.md`` for the pattern.
"""

from __future__ import annotations

from shared_postgres import TeamSchema

SCHEMA = TeamSchema(
    team="social_media_marketing",
    database=None,
    statements=[
        """CREATE TABLE IF NOT EXISTS social_media_posts (
            id              TEXT PRIMARY KEY,
            brand_id        TEXT NOT NULL,
            campaign_name   TEXT NOT NULL,
            platform        TEXT NOT NULL,
            archetype       TEXT NOT NULL DEFAULT '',
            concept_title   TEXT NOT NULL,
            concept_text    TEXT NOT NULL DEFAULT '',
            post_copy       TEXT NOT NULL DEFAULT '',
            content_format  TEXT NOT NULL DEFAULT '',
            cta_variant     TEXT NOT NULL DEFAULT '',
            keywords        JSONB NOT NULL DEFAULT '[]'::jsonb,
            semantic_summary TEXT NOT NULL DEFAULT '',
            engagement_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
            engagement_score FLOAT NOT NULL DEFAULT 0.0,
            posted_at       TIMESTAMPTZ,
            source_job_id   TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        """CREATE INDEX IF NOT EXISTS idx_smp_brand_platform
            ON social_media_posts(brand_id, platform)""",
        """CREATE INDEX IF NOT EXISTS idx_smp_engagement
            ON social_media_posts(platform, engagement_score DESC)""",
        """CREATE INDEX IF NOT EXISTS idx_smp_archetype_platform
            ON social_media_posts(archetype, platform)""",
    ],
    table_names=["social_media_posts"],
)
