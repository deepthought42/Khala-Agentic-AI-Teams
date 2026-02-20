"""Task Generator agent: generates TaskAssignment from merged spec analysis."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from shared.llm import LLMClient
from shared.task_parsing import parse_assignment_from_data
from shared.task_validation import validate_assignment

from shared.context_sizing import (
    compute_task_generator_arch_chars,
    compute_task_generator_existing_chars,
    compute_task_generator_features_chars,
    compute_task_generator_spec_chars,
)
from .models import TaskGeneratorInput
from .prompts import TASK_GENERATOR_CONTEXT_NOTE

logger = logging.getLogger(__name__)

MAX_TASK_GENERATOR_RETRIES = 6


class TaskGeneratorAgent:
    """
    Generates TaskAssignment from merged spec analysis and capped context.
    Used as fallback when the planning pipeline (Backend + Frontend planners) does not produce output.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        assert llm_client is not None, "llm_client is required"
        self.llm = llm_client

    def run(self, input_data: TaskGeneratorInput) -> Dict[str, Any]:
        """
        Generate task plan from merged analysis and capped inputs.
        Returns raw LLM dict (tasks, execution_order, rationale, etc.) for the caller to parse.
        Caller should use parse_assignment_from_data() and validate_assignment().
        """
        # Lazy import to avoid circular dependency with tech_lead_agent
        from tech_lead_agent.prompts import TECH_LEAD_PROMPT

        reqs = input_data.requirements
        merged = input_data.merged_spec_analysis
        max_codebase = compute_task_generator_spec_chars(self.llm)
        max_spec = compute_task_generator_spec_chars(self.llm)
        max_existing = compute_task_generator_existing_chars(self.llm)
        max_features = compute_task_generator_features_chars(self.llm)
        codebase = (input_data.codebase_analysis or "")[:max_codebase]
        spec_trunc = (input_data.spec_content_truncated or "")[:max_spec]
        existing = (input_data.existing_codebase or "")[:max_existing]
        features = (input_data.features_doc or "")[:max_features]

        context_parts = [
            TASK_GENERATOR_CONTEXT_NOTE,
            f"**Product Title:** {reqs.title}",
            f"**Description:** {reqs.description}",
            "**Acceptance Criteria:**",
            *[f"- {c}" for c in reqs.acceptance_criteria],
            "**Constraints:**",
            *[f"- {c}" for c in reqs.constraints],
            f"**Priority:** {reqs.priority}",
        ]

        if input_data.open_questions:
            context_parts.extend([
                "",
                "**OPEN QUESTIONS (resolve with enterprise-informed best-practice defaults; see Step 0 in instructions):**",
                *[f"- {q}" for q in input_data.open_questions],
            ])
        if input_data.assumptions:
            context_parts.extend([
                "",
                "**Assumptions from Spec Intake (may extend when resolving open questions):**",
                *[f"- {a}" for a in input_data.assumptions],
            ])

        if input_data.project_overview:
            po = input_data.project_overview
            context_parts.extend([
                "",
                "**Project Overview:**",
                f"- Primary goal: {po.get('primary_goal', '')}",
                f"- Delivery strategy: {po.get('delivery_strategy', '')}",
                "- Milestones: " + ", ".join(m.get("name", "") for m in po.get("milestones", [])),
            ])

        if features:
            context_parts.extend([
                "",
                "**Features and Functionality (required):**",
                "---",
                features,
                "---",
            ])

        if input_data.alignment_feedback or input_data.conformance_issues:
            feedback_lines = []
            if input_data.alignment_feedback:
                feedback_lines.append("**Alignment feedback:**")
                feedback_lines.extend(f"- {x}" for x in input_data.alignment_feedback)
            if input_data.conformance_issues:
                feedback_lines.append("**Spec conformance – address these:**")
                feedback_lines.extend(f"- {x}" for x in input_data.conformance_issues)
            context_parts.extend(["", "**Planning review feedback:**", "\n".join(feedback_lines)])

        if input_data.repo_path:
            context_parts.extend(["", f"**Repo path:** {input_data.repo_path}"])

        context_parts.extend([
            "",
            "**DEEP SPEC ANALYSIS (from prior chunk+merge – use this for complete coverage):**",
            "---",
            merged,
            "---",
        ])

        if spec_trunc:
            context_parts.extend([
                "",
                "**Truncated initial_spec.md (reference only):**",
                "---",
                spec_trunc,
                "---",
            ])

        if codebase:
            context_parts.extend([
                "",
                "**CODEBASE ANALYSIS:**",
                "---",
                codebase,
                "---",
            ])

        if existing:
            context_parts.extend([
                "",
                "**EXISTING CODE (sample):**",
                "---",
                existing,
                "---",
            ])

        if input_data.architecture:
            arch = input_data.architecture
            max_arch = compute_task_generator_arch_chars(self.llm)
            arch_doc = (arch.architecture_document or "")[:max_arch]
            context_parts.extend([
                "",
                "**System Architecture:**",
                arch.overview,
                "",
                "**Components:**",
                *[f"- {c.name} ({c.type}): {c.description}" for c in arch.components],
                "",
                "**Architecture Document (excerpt):**",
                arch_doc,
            ])

        base_prompt = TECH_LEAD_PROMPT + "\n\n---\n\n" + "\n".join(context_parts)
        validation_feedback = ""

        for attempt in range(MAX_TASK_GENERATOR_RETRIES):
            prompt = base_prompt
            if validation_feedback:
                prompt += "\n\n**VALIDATION FAILED – Fix these issues:**\n" + validation_feedback

            data = self.llm.complete_json(prompt, temperature=0.2)

            if data.get("spec_clarification_needed"):
                return data

            try:
                assignment = parse_assignment_from_data(data)
            except Exception as e:
                logger.warning("TaskGenerator: parse failed on attempt %d: %s", attempt + 1, e)
                validation_feedback = f"Parse error: {e}. Ensure valid JSON with tasks and execution_order."
                continue

            is_valid, errors = validate_assignment(
                assignment,
                requirements=reqs,
                requirement_task_mapping=data.get("requirement_task_mapping"),
            )
            if is_valid:
                return data

            validation_feedback = "\n".join(errors[:15])
            if len(errors) > 15:
                validation_feedback += f"\n... and {len(errors) - 15} more"

        return data
