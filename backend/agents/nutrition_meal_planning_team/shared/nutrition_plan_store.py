"""Postgres-backed storage for nutrition plans with profile-hash cache invalidation.

Each client has at most one cached plan row in ``nutrition_plans``;
``save_plan`` is an upsert so a regenerated plan replaces the prior
cached value.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from shared_postgres import Json, dict_row, get_conn
from shared_postgres.metrics import timed_query

from ..models import ClientProfile, NutritionPlan

logger = logging.getLogger(__name__)

_STORE = "nutrition_meal_planning"


def _profile_hash(profile: ClientProfile) -> str:
    """Deterministic hash of the profile fields that affect nutrition plan generation."""
    data = profile.model_dump(exclude={"client_id", "updated_at"})
    raw = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class NutritionPlanStore:
    """Postgres-backed store for nutrition plans with profile-hash cache invalidation."""

    def __init__(self) -> None:
        # Stateless; the connection pool lives inside shared_postgres.
        pass

    @timed_query(store=_STORE, op="get_cached_plan")
    def get_cached_plan(self, client_id: str, profile: ClientProfile) -> Optional[NutritionPlan]:
        """Return cached plan if it was generated from the same profile state, else None."""
        with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT profile_hash, plan FROM nutrition_plans WHERE client_id = %s",
                (client_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        if row["profile_hash"] != _profile_hash(profile):
            return None
        try:
            return NutritionPlan.model_validate(row["plan"])
        except Exception:
            logger.warning("Failed to parse cached nutrition plan for %s", client_id, exc_info=True)
            return None

    @timed_query(store=_STORE, op="save_plan")
    def save_plan(self, client_id: str, profile: ClientProfile, plan: NutritionPlan) -> None:
        """Save (upsert) a nutrition plan alongside the profile hash it was generated from."""
        ts = datetime.now(tz=timezone.utc)
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO nutrition_plans (client_id, profile_hash, plan, generated_at) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (client_id) DO UPDATE "
                "SET profile_hash = EXCLUDED.profile_hash, "
                "    plan = EXCLUDED.plan, "
                "    generated_at = EXCLUDED.generated_at",
                (client_id, _profile_hash(profile), Json(plan.model_dump()), ts),
            )


# ---------------------------------------------------------------------------
# Lazy singleton
# ---------------------------------------------------------------------------

_default_store: Optional[NutritionPlanStore] = None


def get_nutrition_plan_store() -> NutritionPlanStore:
    """Return the process-wide store, instantiating on first call."""
    global _default_store
    if _default_store is None:
        _default_store = NutritionPlanStore()
    return _default_store
