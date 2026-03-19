"""Agent façade for Medium statistics collection."""

from __future__ import annotations

from .models import MediumStatsReport, MediumStatsRunConfig
from .scraper import collect_medium_stats


class BlogMediumStatsAgent:
    """Collects Medium post statistics via Playwright."""

    def collect(self, config: MediumStatsRunConfig | None = None) -> MediumStatsReport:
        cfg = config or MediumStatsRunConfig()
        return collect_medium_stats(cfg)
