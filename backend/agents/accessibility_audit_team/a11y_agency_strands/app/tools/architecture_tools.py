"""Tools for loading and scoring the Site Architecture & Navigation Accessibility Audit template."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..models.architecture import (
    ArchitectureAuditResult,
    ArchitectureChecklistItem,
    ArchitectureSectionResult,
    WCAGCriterionStatus,
)

_ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"
_TEMPLATE_CACHE: dict | None = None

# ---------------------------------------------------------------------------
# Grading scale (mirrored from YAML for runtime use)
# ---------------------------------------------------------------------------
_GRADING_SCALE = [
    (90, "Excellent"),
    (75, "Good"),
    (50, "Needs Improvement"),
    (0, "Poor"),
]


def _pct_to_grade(pct: float) -> str:
    for threshold, label in _GRADING_SCALE:
        if pct >= threshold:
            return label
    return "Poor"


# ---------------------------------------------------------------------------
# Template loading
# ---------------------------------------------------------------------------


def load_architecture_audit_template() -> dict:
    """Load and cache the site architecture audit template YAML asset.

    Returns:
        Parsed YAML dict with ``sections``, ``scoring``, ``methodology``, etc.
    """
    global _TEMPLATE_CACHE
    if _TEMPLATE_CACHE is None:
        path = _ASSETS_DIR / "site_architecture_audit_template.yaml"
        with open(path) as fh:
            _TEMPLATE_CACHE = yaml.safe_load(fh)
    return _TEMPLATE_CACHE


# ---------------------------------------------------------------------------
# Section scoring
# ---------------------------------------------------------------------------


def score_architecture_section(
    section_id: str,
    section_name: str,
    results: list[dict[str, Any]],
) -> ArchitectureSectionResult:
    """Score a single architecture audit section from checklist results.

    Args:
        section_id: Identifier of the section being scored.
        section_name: Display name.
        results: List of dicts, each with at least ``id``, ``label``,
            ``passed`` (bool), and optionally ``notes``, ``wcag_ref``,
            ``test_method``.

    Returns:
        :class:`ArchitectureSectionResult` with counts, percentage, and grade.
    """
    items = [ArchitectureChecklistItem(**r) for r in results]
    total = len(items)
    passed = sum(1 for it in items if it.passed)
    pct = (passed / total * 100) if total else 0.0
    issues = [it.label for it in items if not it.passed]

    return ArchitectureSectionResult(
        section_id=section_id,
        name=section_name,
        items=items,
        passed_count=passed,
        total_count=total,
        score_pct=round(pct, 1),
        grade=_pct_to_grade(pct),
        issues=issues,
    )


# ---------------------------------------------------------------------------
# Full report assembly
# ---------------------------------------------------------------------------


def _collect_wcag_statuses(sections: list[ArchitectureSectionResult]) -> list[WCAGCriterionStatus]:
    """Derive per-criterion pass/fail status from scored section items."""
    sc_map: dict[str, dict] = {}
    for section in sections:
        for item in section.items:
            if not item.wcag_ref:
                continue
            if item.wcag_ref not in sc_map:
                sc_map[item.wcag_ref] = {"items": [], "passed": [], "failed": []}
            sc_map[item.wcag_ref]["items"].append(item.id)
            if item.passed:
                sc_map[item.wcag_ref]["passed"].append(item.id)
            else:
                sc_map[item.wcag_ref]["failed"].append(item.id)

    statuses: list[WCAGCriterionStatus] = []
    for sc, data in sorted(sc_map.items()):
        if data["failed"]:
            status = "fail" if not data["passed"] else "partial"
        else:
            status = "pass"
        statuses.append(
            WCAGCriterionStatus(
                sc=sc,
                status=status,
                related_items=data["items"],
            )
        )
    return statuses


def build_architecture_audit_report(
    target: str,
    section_results: list[ArchitectureSectionResult],
    recommendations: list[str] | None = None,
) -> ArchitectureAuditResult:
    """Assemble a full architecture audit report from scored sections.

    Args:
        target: Site URL or identifier.
        section_results: Scored section results from
            :func:`score_architecture_section`.
        recommendations: Optional prioritized recommendation strings.

    Returns:
        :class:`ArchitectureAuditResult` with overall score, grade, WCAG
        compliance mapping, and recommendations.
    """
    total_items = sum(s.total_count for s in section_results)
    total_passed = sum(s.passed_count for s in section_results)
    overall_pct = (total_passed / total_items * 100) if total_items else 0.0

    wcag_compliance = _collect_wcag_statuses(section_results)

    return ArchitectureAuditResult(
        target=target,
        sections=section_results,
        overall_score_pct=round(overall_pct, 1),
        overall_grade=_pct_to_grade(overall_pct),
        wcag_compliance=wcag_compliance,
        recommendations=recommendations or [],
    )
