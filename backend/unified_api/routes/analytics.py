"""
Agent performance analytics API.

Endpoints:
- GET /api/analytics/team/{team}/scorecard  — team quality scorecard
- GET /api/analytics/signals                — raw signal history
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

_agents_dir = Path(__file__).resolve().parent.parent.parent / "agents"
if str(_agents_dir) not in sys.path:
    sys.path.insert(0, str(_agents_dir))

from analytics.signals import get_signals, get_team_scorecard  # noqa: E402

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/team/{team}/scorecard")
def team_scorecard(
    team: str,
    window: float = Query(24.0, description="Time window in hours"),
) -> Dict[str, Any]:
    """Quality scorecard for a team: pass rates, retry counts, build success, etc."""
    return get_team_scorecard(team, window_hours=window)


@router.get("/signals")
def signal_history(
    team: Optional[str] = Query(None),
    signal_type: Optional[str] = Query(None),
    window: float = Query(24.0),
    limit: int = Query(100, ge=1, le=1000),
) -> List[Dict[str, Any]]:
    """Raw quality signal events, filterable by team and type."""
    from analytics.signals import SignalType

    st = None
    if signal_type:
        try:
            st = SignalType(signal_type)
        except ValueError:
            pass
    return get_signals(team=team, signal_type=st, window_hours=window, limit=limit)
