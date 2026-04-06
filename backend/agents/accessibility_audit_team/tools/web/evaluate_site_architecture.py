"""
Tool: web.evaluate_site_architecture

Evaluate site architecture and navigation for accessibility using the
structured audit template.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Template loading (shared asset)
# ---------------------------------------------------------------------------

_ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "a11y_agency_strands" / "assets"
_TEMPLATE_CACHE: dict | None = None

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


def _load_template() -> dict:
    global _TEMPLATE_CACHE
    if _TEMPLATE_CACHE is None:
        path = _ASSETS_DIR / "site_architecture_audit_template.yaml"
        with open(path) as fh:
            _TEMPLATE_CACHE = yaml.safe_load(fh)
    return _TEMPLATE_CACHE


# ---------------------------------------------------------------------------
# I/O models
# ---------------------------------------------------------------------------


class ChecklistItemResult(BaseModel):
    """Result for a single checklist item."""

    id: str
    passed: bool
    notes: str = ""


class SectionScore(BaseModel):
    """Scored result for one template section."""

    section_id: str
    name: str
    passed_count: int = 0
    total_count: int = 0
    score_pct: float = 0.0
    grade: str = ""
    failing_items: List[str] = Field(default_factory=list)


class WCAGCriterionResult(BaseModel):
    """Per-criterion pass/fail derived from checklist items."""

    sc: str
    status: str = "not_tested"
    related_items: List[str] = Field(default_factory=list)


class EvaluateSiteArchitectureInput(BaseModel):
    """Input for evaluating site architecture accessibility."""

    audit_id: str = Field(..., description="Audit identifier")
    url: str = Field(..., description="Root URL of the site being audited")
    checklist_overrides: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="Map of checklist item ID to {passed: bool, notes: str}",
    )
    recommendations: Optional[List[str]] = Field(
        default=None,
        description="Prioritized recommendation strings",
    )


class EvaluateSiteArchitectureOutput(BaseModel):
    """Output from site architecture evaluation."""

    url: str
    template_version: str = "1.0"
    section_scores: List[SectionScore] = Field(default_factory=list)
    overall_score_pct: float = 0.0
    overall_grade: str = ""
    wcag_compliance: List[WCAGCriterionResult] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    raw_ref: str = Field(default="", description="Reference to raw results artifact")


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------


def _flatten_items(section_def: dict) -> list[dict]:
    items: list[dict] = []
    for sub in section_def.get("subsections", []):
        for item in sub.get("checklist_items", []):
            items.append(item)
    return items


async def evaluate_site_architecture(
    input_data: EvaluateSiteArchitectureInput,
) -> EvaluateSiteArchitectureOutput:
    """Evaluate site architecture and navigation accessibility.

    Loads the structured audit template, applies any checklist result
    overrides from ``input_data``, scores each section, and returns
    an overall assessment with WCAG compliance mapping.

    This tool is typically called by the Web Audit Specialist (WAS)
    or a dedicated Architecture Auditor during the architecture_audit phase.
    """
    template = _load_template()
    overrides = input_data.checklist_overrides

    section_scores: list[SectionScore] = []
    # Track per-SC results for WCAG compliance mapping
    sc_map: dict[str, dict] = {}

    for section_def in template.get("sections", []):
        section_id = section_def["id"]
        section_name = section_def["name"]
        template_items = _flatten_items(section_def)

        total = len(template_items)
        passed = 0
        failing: list[str] = []

        for item in template_items:
            item_id = item["id"]
            override = overrides.get(item_id, {})
            item_passed = override.get("passed", False)

            if item_passed:
                passed += 1
            else:
                failing.append(item.get("label", item_id))

            # Aggregate WCAG criterion status
            wcag_ref = item.get("wcag_ref")
            if wcag_ref:
                if wcag_ref not in sc_map:
                    sc_map[wcag_ref] = {"items": [], "passed": [], "failed": []}
                sc_map[wcag_ref]["items"].append(item_id)
                if item_passed:
                    sc_map[wcag_ref]["passed"].append(item_id)
                else:
                    sc_map[wcag_ref]["failed"].append(item_id)

        pct = (passed / total * 100) if total else 0.0
        section_scores.append(
            SectionScore(
                section_id=section_id,
                name=section_name,
                passed_count=passed,
                total_count=total,
                score_pct=round(pct, 1),
                grade=_pct_to_grade(pct),
                failing_items=failing,
            )
        )

    # Overall score
    total_items = sum(s.total_count for s in section_scores)
    total_passed = sum(s.passed_count for s in section_scores)
    overall_pct = (total_passed / total_items * 100) if total_items else 0.0

    # WCAG compliance
    wcag_compliance: list[WCAGCriterionResult] = []
    for sc, data in sorted(sc_map.items()):
        if data["failed"]:
            status = "fail" if not data["passed"] else "partial"
        else:
            status = "pass"
        wcag_compliance.append(
            WCAGCriterionResult(sc=sc, status=status, related_items=data["items"])
        )

    return EvaluateSiteArchitectureOutput(
        url=input_data.url,
        section_scores=section_scores,
        overall_score_pct=round(overall_pct, 1),
        overall_grade=_pct_to_grade(overall_pct),
        wcag_compliance=wcag_compliance,
        recommendations=input_data.recommendations or [],
        raw_ref=f"arch_audit_{input_data.audit_id}_{hash(input_data.url) % 10000}",
    )
