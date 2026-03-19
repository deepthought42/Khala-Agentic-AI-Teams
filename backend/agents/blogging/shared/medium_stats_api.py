"""HTTP request body for Medium stats endpoints.

Defined outside api/main.py so FastAPI can resolve the model when main uses
``from __future__ import annotations`` (PEP 563).
"""

from typing import Optional

from pydantic import BaseModel, Field


class MediumStatsRequest(BaseModel):
    """Options for Medium statistics collection."""

    headless: bool = True
    timeout_ms: int = Field(90_000, ge=5000, le=600_000)
    max_posts: Optional[int] = Field(None, ge=1)
    storage_state_path: Optional[str] = Field(
        None,
        description="Playwright storage_state JSON path; overrides MEDIUM_STORAGE_STATE_PATH.",
    )
    medium_email: Optional[str] = Field(None, description="Overrides MEDIUM_EMAIL when set.")
    medium_password: Optional[str] = Field(
        None,
        description="Overrides MEDIUM_PASSWORD when set. Prefer env or storage state in production.",
    )
