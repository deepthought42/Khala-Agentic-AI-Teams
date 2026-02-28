"""
UI Design tool agent for planning-v2.

Participates in phases: Planning, Implementation.
Focuses on visual design, component library, and design system planning.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ...models import ToolAgentPhaseInput, ToolAgentPhaseOutput
from ..json_utils import parse_json_with_recovery, default_decompose_by_sections

if TYPE_CHECKING:
    from shared.llm import LLMClient

logger = logging.getLogger(__name__)


def _merge_ui_design_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge UI design results from multiple chunks."""
    merged: Dict[str, Any] = {
        "design_tokens": {},
        "components": [],
        "layouts": [],
        "breakpoints": {},
        "accessibility": [],
        "recommendations": [],
        "summary": "",
    }
    summaries = []

    for r in results:
        if isinstance(r.get("design_tokens"), dict):
            for k, v in r["design_tokens"].items():
                if k not in merged["design_tokens"]:
                    merged["design_tokens"][k] = v
                elif isinstance(v, list) and isinstance(merged["design_tokens"][k], list):
                    merged["design_tokens"][k].extend(v)
        if isinstance(r.get("components"), list):
            for c in r["components"]:
                if c not in merged["components"]:
                    merged["components"].append(c)
        if isinstance(r.get("layouts"), list):
            for lay in r["layouts"]:
                if lay not in merged["layouts"]:
                    merged["layouts"].append(lay)
        if isinstance(r.get("breakpoints"), dict):
            merged["breakpoints"].update(r["breakpoints"])
        if isinstance(r.get("accessibility"), list):
            merged["accessibility"].extend(r["accessibility"])
        if isinstance(r.get("recommendations"), list):
            merged["recommendations"].extend(r["recommendations"])
        if r.get("summary"):
            summaries.append(str(r["summary"]))

    merged["summary"] = f"Merged {len(results)} sections. " + " ".join(summaries[:2])
    return merged

UI_DESIGN_PLANNING_PROMPT = """You are a UI Design expert. Create a UI design plan for:

Specification:
---
{spec_content}
---

Plan for:
1. Design system (colors, typography, spacing)
2. Component library (buttons, forms, cards, etc.)
3. Page layouts and templates
4. Responsive breakpoints
5. Accessibility considerations

Respond with JSON:
{{
  "design_tokens": {{"colors": ["primary", "secondary"], "typography": ["heading", "body"], "spacing": ["sm", "md", "lg"]}},
  "components": ["Button", "Card", "Form", "Modal", "Navigation"],
  "layouts": ["Dashboard", "Detail", "List", "Auth"],
  "breakpoints": {{"mobile": "320px", "tablet": "768px", "desktop": "1024px"}},
  "accessibility": ["WCAG 2.1 AA", "keyboard navigation", "screen reader support"],
  "recommendations": ["ui design recommendations"],
  "summary": "brief summary"
}}
"""

UI_DESIGN_PLANNING_CHUNK_PROMPT = """You are a UI Design expert. Analyze this SECTION for UI design:

SECTION:
---
{chunk_content}
---

Respond with concise JSON for THIS section only:
{{
  "design_tokens": {{"relevant": "tokens"}},
  "components": ["components needed"],
  "layouts": ["layouts needed"],
  "accessibility": ["considerations"],
  "recommendations": ["recommendations"],
  "summary": "brief summary"
}}
"""


class UIDesignToolAgent:
    """
    UI Design tool agent: visual design, component library, design system.
    
    Participates in Planning and Implementation phases per the matrix.
    """

    def __init__(self, llm: Optional["LLMClient"] = None) -> None:
        self.llm = llm

    def plan(self, inp: ToolAgentPhaseInput) -> ToolAgentPhaseOutput:
        """Planning phase: create UI design plan."""
        if not self.llm:
            return ToolAgentPhaseOutput(
                summary="UI Design planning skipped (no LLM).",
                recommendations=["Define design tokens", "Plan component library"],
            )
        
        spec_content = inp.spec_content or ""
        prompt = UI_DESIGN_PLANNING_PROMPT.format(
            spec_content=spec_content[:6000],
        )
        data = parse_json_with_recovery(
            self.llm,
            prompt,
            agent_name="UIDesign",
            decompose_fn=default_decompose_by_sections,
            merge_fn=_merge_ui_design_results,
            original_content=spec_content,
            chunk_prompt_template=UI_DESIGN_PLANNING_CHUNK_PROMPT,
        )
        
        recommendations = data.get("recommendations") or []
        if not isinstance(recommendations, list):
            recommendations = [str(recommendations)]
        
        return ToolAgentPhaseOutput(
            summary=data.get("summary", "UI Design planning complete."),
            recommendations=recommendations,
            metadata={
                "design_tokens": data.get("design_tokens", {}),
                "components": data.get("components", []),
                "layouts": data.get("layouts", []),
                "breakpoints": data.get("breakpoints", {}),
                "accessibility": data.get("accessibility", []),
            },
        )

    def execute(self, inp: ToolAgentPhaseInput) -> ToolAgentPhaseOutput:
        """Implementation phase: generate UI design artifacts."""
        design_tokens = inp.metadata.get("design_tokens", {})
        components = inp.metadata.get("components", [])
        layouts = inp.metadata.get("layouts", [])
        breakpoints = inp.metadata.get("breakpoints", {})
        accessibility = inp.metadata.get("accessibility", [])
        
        content_parts = ["# UI Design Plan\n\n"]
        
        if design_tokens:
            content_parts.append("## Design Tokens\n")
            for category, tokens in design_tokens.items():
                content_parts.append(f"### {category.title()}\n")
                if isinstance(tokens, list):
                    for token in tokens:
                        content_parts.append(f"- {token}\n")
                else:
                    content_parts.append(f"- {tokens}\n")
            content_parts.append("\n")
        
        if components:
            content_parts.append("## Component Library\n")
            for comp in components:
                content_parts.append(f"- {comp}\n")
            content_parts.append("\n")
        
        if layouts:
            content_parts.append("## Page Layouts\n")
            for layout in layouts:
                content_parts.append(f"- {layout}\n")
            content_parts.append("\n")
        
        if breakpoints:
            content_parts.append("## Responsive Breakpoints\n")
            for name, value in breakpoints.items():
                content_parts.append(f"- **{name}:** {value}\n")
            content_parts.append("\n")
        
        if accessibility:
            content_parts.append("## Accessibility\n")
            for item in accessibility:
                content_parts.append(f"- {item}\n")
            content_parts.append("\n")
        
        files = {}
        if design_tokens or components:
            files["plan/ui_design.md"] = "".join(content_parts)
        
        return ToolAgentPhaseOutput(
            summary="UI Design artifacts generated.",
            files=files,
        )

    def review(self, inp: ToolAgentPhaseInput) -> ToolAgentPhaseOutput:
        """Review phase: UI Design does not participate."""
        return ToolAgentPhaseOutput(summary="UI Design review not applicable (per matrix).")

    def problem_solve(self, inp: ToolAgentPhaseInput) -> ToolAgentPhaseOutput:
        """Problem-solving phase: UI Design does not participate."""
        return ToolAgentPhaseOutput(summary="UI Design problem_solve not applicable (per matrix).")

    def deliver(self, inp: ToolAgentPhaseInput) -> ToolAgentPhaseOutput:
        """Deliver phase: UI Design does not participate."""
        return ToolAgentPhaseOutput(summary="UI Design deliver not applicable (per matrix).")
