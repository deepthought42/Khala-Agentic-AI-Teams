"""Postgres schema for the nutrition & meal planning team.

Ports the four file-based stores under
``nutrition_meal_planning_team/shared/`` (client profiles, conversation
history, nutrition plans, meal recommendations + feedback) to Postgres.
Registered from the team's FastAPI lifespan via
``shared_postgres.register_team_schemas``.

This module is pure data — importing it has no side effects. DDL runs
only when ``register_team_schemas(SCHEMA)`` is invoked at startup.
"""

from __future__ import annotations

from shared_postgres import TeamSchema

SCHEMA = TeamSchema(
    team="nutrition_meal_planning",
    database=None,
    statements=[
        """CREATE TABLE IF NOT EXISTS nutrition_profiles (
            client_id   TEXT PRIMARY KEY,
            profile     JSONB NOT NULL,
            updated_at  TIMESTAMPTZ NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS nutrition_conversations (
            id         BIGSERIAL PRIMARY KEY,
            client_id  TEXT NOT NULL,
            role       TEXT NOT NULL,
            content    TEXT NOT NULL,
            phase      TEXT,
            action     TEXT,
            timestamp  TIMESTAMPTZ NOT NULL
        )""",
        """CREATE INDEX IF NOT EXISTS idx_nutrition_conversations_client
            ON nutrition_conversations(client_id, id)""",
        """CREATE TABLE IF NOT EXISTS nutrition_plans (
            client_id     TEXT PRIMARY KEY,
            profile_hash  TEXT NOT NULL,
            plan          JSONB NOT NULL,
            generated_at  TIMESTAMPTZ NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS nutrition_recommendations (
            recommendation_id         TEXT PRIMARY KEY,
            client_id                 TEXT NOT NULL,
            meal_snapshot             JSONB NOT NULL,
            recommended_at            TIMESTAMPTZ NOT NULL,
            feedback_rating           INTEGER,
            feedback_would_make_again BOOLEAN,
            feedback_notes            TEXT,
            feedback_submitted_at     TIMESTAMPTZ
        )""",
        """CREATE INDEX IF NOT EXISTS idx_nutrition_recommendations_client_time
            ON nutrition_recommendations(client_id, recommended_at DESC)""",
    ],
    table_names=[
        "nutrition_profiles",
        "nutrition_conversations",
        "nutrition_plans",
        "nutrition_recommendations",
    ],
)
