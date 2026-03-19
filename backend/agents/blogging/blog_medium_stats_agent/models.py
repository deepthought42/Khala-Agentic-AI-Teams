"""Pydantic models for Medium stats collection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MediumPostStats(BaseModel):
    """Per-story metrics scraped from the stats UI."""

    title: str = ""
    url: str = ""
    stats: Dict[str, Any] = Field(default_factory=dict)
    raw_row_text: str = Field("", description="Nearby text for debugging when parsing fails")


class MediumStatsReport(BaseModel):
    """Serialized to medium_stats_report.json."""

    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="UTC ISO-8601 timestamp",
    )
    source: str = "medium.com"
    account_hint: str = Field(
        "",
        description="Non-sensitive hint (e.g. email domain only)",
    )
    posts: List[MediumPostStats] = Field(default_factory=list)
    raw_warnings: List[str] = Field(default_factory=list)


class MediumStatsRunConfig(BaseModel):
    """Runtime options for one scrape run."""

    headless: bool = True
    timeout_ms: int = Field(90_000, ge=5_000, le=600_000)
    max_posts: Optional[int] = Field(None, ge=1, description="Cap rows returned after dedupe")
    # Test-only: bypass integration store when set
    storage_state_override: Optional[Dict[str, Any]] = Field(
        default=None,
        description="If set, use this Playwright storage_state instead of the platform integration.",
    )
    account_hint_override: str = Field(
        "",
        description="With storage_state_override, optional hint for the report.",
    )
