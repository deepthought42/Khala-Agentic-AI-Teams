"""Architecture Auditor — evaluates site navigation and IA for accessibility."""

from __future__ import annotations

from ..tools import persist_artifact
from ..tools.architecture_tools import (
    build_architecture_audit_report,
    load_architecture_audit_template,
    score_architecture_section,
)
from .base import ToolContext, tool


def _flatten_checklist_items(section_def: dict) -> list[dict]:
    """Extract all checklist items from a template section, including subsections."""
    items: list[dict] = []
    for sub in section_def.get("subsections", []):
        for item in sub.get("checklist_items", []):
            items.append(item)
    return items


@tool(context=True)
def run_architecture_audit(target: str, tool_context: ToolContext) -> dict:
    """Run the site architecture and navigation accessibility audit.

    Loads the structured audit template, evaluates each section's checklist
    items against the provided results in ``tool_context.invocation_state``,
    scores every section, and assembles the full audit report.

    ``tool_context.invocation_state`` may contain:

    * ``artifact_root`` — directory for persisting the output artifact.
    * ``checklist_results`` — dict mapping checklist item IDs to
      ``{"passed": bool, "notes": str}`` overrides.  Items not present
      in this mapping default to ``passed=False``.
    * ``recommendations`` — optional list of prioritized recommendation
      strings to include in the report.
    """
    template = load_architecture_audit_template()
    state = tool_context.invocation_state
    overrides: dict = state.get("checklist_results", {})
    recommendations: list[str] = state.get("recommendations", [])

    section_results = []
    for section_def in template.get("sections", []):
        section_id = section_def["id"]
        section_name = section_def["name"]
        template_items = _flatten_checklist_items(section_def)

        evaluated: list[dict] = []
        for item in template_items:
            item_id = item["id"]
            override = overrides.get(item_id, {})
            evaluated.append(
                {
                    "id": item_id,
                    "label": item.get("label", ""),
                    "passed": override.get("passed", False),
                    "notes": override.get("notes", ""),
                    "wcag_ref": item.get("wcag_ref"),
                    "test_method": item.get("test_method", ""),
                }
            )

        scored = score_architecture_section(section_id, section_name, evaluated)
        section_results.append(scored)

    report = build_architecture_audit_report(target, section_results, recommendations)
    artifact_path = f"{state['artifact_root']}/architecture.json"
    artifact = persist_artifact(artifact_path, report.model_dump())

    return {
        "phase": "architecture_audit",
        "artifact": artifact,
        "overall_grade": report.overall_grade,
    }
