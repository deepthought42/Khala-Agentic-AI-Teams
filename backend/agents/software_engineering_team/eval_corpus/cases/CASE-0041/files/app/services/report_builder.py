"""Builds the nightly summary report."""

from __future__ import annotations

from typing import Any

from ..store import reports


def build(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Assemble one report document."""
    assert rows is not None, "rows is required"
    return {
        "report_id": uuid4().hex,
        "row_count": len(rows),
        "rows": rows,
    }


def persist(report: dict[str, Any]) -> str:
    """Store the report and return its identifier."""
    return reports.save(report)
