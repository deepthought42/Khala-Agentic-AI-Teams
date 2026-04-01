"""Storage for meal recommendations and feedback (Nutrition & Meal Planning team)."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from ..models import FeedbackRecord, MealHistoryEntry

logger = logging.getLogger(__name__)


def _default_storage_dir() -> Path:
    base = os.environ.get("AGENT_CACHE", ".agent_cache")
    return Path(base) / "nutrition_meal_planning_team" / "recommendations"


def _recommendation_path(
    storage_dir: Path, recommendation_id: str, client_id: Optional[str] = None
) -> Path:
    if client_id:
        return storage_dir / client_id / f"{recommendation_id}.json"
    # Fallback: search all client subdirectories (for feedback by recommendation_id only)
    if storage_dir.exists():
        for client_dir in storage_dir.iterdir():
            if client_dir.is_dir():
                candidate = client_dir / f"{recommendation_id}.json"
                if candidate.exists():
                    return candidate
    # Legacy flat layout fallback
    return storage_dir / f"{recommendation_id}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, content: str, directory: Path) -> None:
    """Write content to path atomically via temp file + rename."""
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def record_recommendation(
    client_id: str,
    meal_snapshot: Dict[str, Any],
    storage_dir: Optional[Path] = None,
) -> str:
    """Store a meal recommendation and return its recommendation_id."""
    directory = storage_dir or _default_storage_dir()
    client_dir = directory / client_id
    client_dir.mkdir(parents=True, exist_ok=True)
    recommendation_id = str(uuid4())
    path = client_dir / f"{recommendation_id}.json"
    payload = {
        "recommendation_id": recommendation_id,
        "client_id": client_id,
        "recommended_at": _now(),
        "meal_snapshot": meal_snapshot,
        "feedback": None,
    }
    _atomic_write(path, json.dumps(payload, indent=2), client_dir)
    return recommendation_id


def record_feedback(
    recommendation_id: str,
    rating: Optional[int] = None,
    would_make_again: Optional[bool] = None,
    notes: Optional[str] = None,
    storage_dir: Optional[Path] = None,
) -> bool:
    """Attach feedback to an existing recommendation. Returns True if found and updated."""
    directory = storage_dir or _default_storage_dir()
    path = _recommendation_path(directory, recommendation_id)
    if not path.exists():
        return False
    payload = json.loads(path.read_text(encoding="utf-8"))
    feedback = payload.get("feedback") or {}
    if rating is not None:
        feedback["rating"] = rating
    if would_make_again is not None:
        feedback["would_make_again"] = would_make_again
    if notes is not None:
        feedback["notes"] = notes
    feedback["recommendation_id"] = recommendation_id
    feedback["submitted_at"] = _now()
    payload["feedback"] = feedback
    _atomic_write(path, json.dumps(payload, indent=2), path.parent)
    return True


def get_meal_history(
    client_id: str,
    limit: int = 50,
    date_range_start: Optional[str] = None,
    date_range_end: Optional[str] = None,
    storage_dir: Optional[Path] = None,
) -> List[MealHistoryEntry]:
    """Return past recommendations with feedback for the client, newest first."""
    directory = storage_dir or _default_storage_dir()
    client_dir = directory / client_id
    # Scan per-client subdirectory first, then legacy flat layout for migration compat
    scan_dirs = []
    if client_dir.exists():
        scan_dirs.append(client_dir)
    if directory.exists():
        scan_dirs.append(directory)
    if not scan_dirs:
        return []
    entries: List[MealHistoryEntry] = []
    seen_ids: set = set()
    for scan_dir in scan_dirs:
        for path in scan_dir.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("client_id") != client_id:
                    continue
                rec_id = payload.get("recommendation_id", "")
                if rec_id in seen_ids:
                    continue
                seen_ids.add(rec_id)
                rec_at = payload.get("recommended_at") or ""
                if date_range_start and rec_at < date_range_start:
                    continue
                if date_range_end and rec_at > date_range_end:
                    continue
                feedback = payload.get("feedback")
                feedback_record = None
                if feedback:
                    feedback_record = FeedbackRecord(
                        recommendation_id=rec_id,
                        rating=feedback.get("rating"),
                        would_make_again=feedback.get("would_make_again"),
                        notes=feedback.get("notes", ""),
                        submitted_at=feedback.get("submitted_at"),
                    )
                entries.append(
                    MealHistoryEntry(
                        recommendation_id=rec_id,
                        client_id=payload.get("client_id", ""),
                        meal_snapshot=payload.get("meal_snapshot", {}),
                        recommended_at=rec_at,
                        feedback=feedback_record,
                    )
                )
            except Exception:
                logger.warning("Failed to load recommendation file %s", path, exc_info=True)
                continue
    entries.sort(key=lambda e: e.recommended_at or "", reverse=True)
    return entries[:limit]


class MealFeedbackStore:
    """Store for meal recommendations and feedback. Use module-level functions or instance methods."""

    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        self.storage_dir = storage_dir or _default_storage_dir()

    def record_recommendation(self, client_id: str, meal_snapshot: Dict[str, Any]) -> str:
        return record_recommendation(client_id, meal_snapshot, self.storage_dir)

    def record_feedback(
        self,
        recommendation_id: str,
        rating: Optional[int] = None,
        would_make_again: Optional[bool] = None,
        notes: Optional[str] = None,
    ) -> bool:
        return record_feedback(recommendation_id, rating, would_make_again, notes, self.storage_dir)

    def get_meal_history(
        self,
        client_id: str,
        limit: int = 50,
        date_range_start: Optional[str] = None,
        date_range_end: Optional[str] = None,
    ) -> List[MealHistoryEntry]:
        return get_meal_history(
            client_id, limit, date_range_start, date_range_end, self.storage_dir
        )
