"""Postgres-backed storage for client profiles (Nutrition & Meal Planning team).

Profiles are stored whole in the ``nutrition_profiles.profile`` JSONB
column keyed by ``client_id``. Saves use upsert semantics so there is at
most one current row per client (matching the pre-migration file layout).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from shared_postgres import Json, dict_row, get_conn
from shared_postgres.metrics import timed_query

from ..models import ClientProfile

logger = logging.getLogger(__name__)

_STORE = "nutrition_meal_planning"


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@timed_query(store=_STORE, op="get_profile")
def get_profile(client_id: str) -> Optional[ClientProfile]:
    """Load client profile by client_id. Returns None if not found."""
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT profile FROM nutrition_profiles WHERE client_id = %s",
            (client_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
    try:
        profile = ClientProfile.model_validate(row["profile"])
    except Exception:
        logger.warning("Corrupt profile JSON for %s", client_id, exc_info=True)
        return None
    profile.client_id = client_id
    return profile


@timed_query(store=_STORE, op="save_profile")
def save_profile(client_id: str, profile: ClientProfile) -> None:
    """Save client profile via upsert. Mutates ``profile.updated_at`` as a side effect."""
    profile.client_id = client_id
    profile.updated_at = _now_iso()
    ts = datetime.now(tz=timezone.utc)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO nutrition_profiles (client_id, profile, updated_at) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (client_id) DO UPDATE "
            "SET profile = EXCLUDED.profile, updated_at = EXCLUDED.updated_at",
            (client_id, Json(profile.model_dump()), ts),
        )


def create_profile(client_id: str) -> ClientProfile:
    """Create a new empty profile for client_id and save it. Returns the new profile."""
    profile = ClientProfile(client_id=client_id)
    save_profile(client_id, profile)
    return profile


class ClientProfileStore:
    """Postgres-backed store for client profiles.

    The constructor takes no arguments — the Postgres DSN is read from
    ``POSTGRES_*`` env vars by ``shared_postgres.get_conn``.
    """

    def __init__(self) -> None:
        # Stateless; the connection pool lives inside shared_postgres.
        pass

    def get_profile(self, client_id: str) -> Optional[ClientProfile]:
        return get_profile(client_id)

    def save_profile(self, client_id: str, profile: ClientProfile) -> None:
        save_profile(client_id, profile)

    def create_profile(self, client_id: str) -> ClientProfile:
        return create_profile(client_id)


# ---------------------------------------------------------------------------
# Lazy singleton
# ---------------------------------------------------------------------------

_default_store: Optional[ClientProfileStore] = None


def get_profile_store() -> ClientProfileStore:
    """Return the process-wide store, instantiating on first call."""
    global _default_store
    if _default_store is None:
        _default_store = ClientProfileStore()
    return _default_store
