"""Storage for nutrition plans with profile-hash-based caching (Nutrition & Meal Planning team)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..models import ClientProfile, NutritionPlan

logger = logging.getLogger(__name__)


def _default_storage_dir() -> Path:
    base = os.environ.get("AGENT_CACHE", ".agent_cache")
    return Path(base) / "nutrition_meal_planning_team" / "nutrition_plans"


def _plan_path(storage_dir: Path, client_id: str) -> Path:
    return storage_dir / f"{client_id}.json"


def _profile_hash(profile: ClientProfile) -> str:
    """Deterministic hash of the profile fields that affect nutrition plan generation."""
    data = profile.model_dump(exclude={"client_id", "updated_at"})
    raw = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class NutritionPlanStore:
    """File-based store for nutrition plans with profile-hash-based cache invalidation."""

    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        self.storage_dir = storage_dir or _default_storage_dir()

    def get_cached_plan(self, client_id: str, profile: ClientProfile) -> Optional[NutritionPlan]:
        """Return cached plan if it was generated from the same profile state, else None."""
        path = _plan_path(self.storage_dir, client_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("profile_hash") != _profile_hash(profile):
                return None
            return NutritionPlan.model_validate(payload["plan"])
        except Exception:
            logger.warning("Failed to load cached nutrition plan for %s", client_id)
            return None

    def save_plan(self, client_id: str, profile: ClientProfile, plan: NutritionPlan) -> None:
        """Save a nutrition plan alongside the profile hash it was generated from."""
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "client_id": client_id,
            "profile_hash": _profile_hash(profile),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "plan": json.loads(plan.model_dump_json()),
        }
        path = _plan_path(self.storage_dir, client_id)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
