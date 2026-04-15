"""Postgres-backed storage for chat conversation history (Nutrition & Meal Planning team).

Each chat turn is stored as a row in ``nutrition_conversations``; messages
are returned ordered by insertion id. Schema is registered from the team's
FastAPI lifespan via ``shared_postgres.register_team_schemas`` — this
module only does data access through ``shared_postgres.get_conn``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from shared_postgres import dict_row, get_conn
from shared_postgres.metrics import timed_query

logger = logging.getLogger(__name__)

_STORE = "nutrition_meal_planning"


def _row_ts(value: Any) -> str:
    """Normalize a Postgres TIMESTAMPTZ to an ISO-8601 string."""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


@timed_query(store=_STORE, op="get_conversation")
def get_conversation(client_id: str) -> List[Dict[str, Any]]:
    """Load conversation history for a client. Returns empty list if not found."""
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT role, content, timestamp, phase, action "
            "FROM nutrition_conversations "
            "WHERE client_id = %s ORDER BY id",
            (client_id,),
        )
        return [
            {
                "role": r["role"],
                "content": r["content"],
                "timestamp": _row_ts(r["timestamp"]),
                "phase": r["phase"],
                "action": r["action"],
            }
            for r in cur.fetchall()
        ]


@timed_query(store=_STORE, op="append_message")
def append_message(
    client_id: str,
    role: str,
    content: str,
    *,
    phase: Optional[str] = None,
    action: Optional[str] = None,
) -> None:
    """Append a single message to the conversation history."""
    ts = datetime.now(tz=timezone.utc)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO nutrition_conversations "
            "(client_id, role, content, phase, action, timestamp) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (client_id, role, content, phase, action, ts),
        )


@timed_query(store=_STORE, op="clear_conversation")
def clear_conversation(client_id: str) -> None:
    """Delete conversation history for a client."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM nutrition_conversations WHERE client_id = %s",
            (client_id,),
        )
