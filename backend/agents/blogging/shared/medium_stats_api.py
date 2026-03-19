"""HTTP request body for Medium stats endpoints.

Defined outside api/main.py so FastAPI can resolve the model when main uses
``from __future__ import annotations`` (PEP 563).
"""

from pydantic import BaseModel, Field


class MediumStatsRequest(BaseModel):
    """Options for Medium statistics collection (auth comes from Integrations → Medium)."""

    headless: bool = True
    timeout_ms: int = Field(90_000, ge=5000, le=600_000)
    max_posts: int | None = Field(None, ge=1)
