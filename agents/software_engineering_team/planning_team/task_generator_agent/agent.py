"""Task Generator agent: generates TaskAssignment from merged spec analysis.

When the LLM response is too large to fit the output token budget (causing
JSON parse failures), the agent recursively decomposes the planning scope
into smaller microtask slices, generates each independently, and merges the
results.  If decomposition still fails after ``MAX_MICROTASK_SPLIT_DEPTH``
levels, an escalation payload is returned for the Tech Lead to refine and
redistribute.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from shared.llm import LLMClient, LLMJsonParseError
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
MAX_MICROTASK_SPLIT_DEPTH = 7

ESCALATION_KEY = "_task_generator_escalation"


class TaskGeneratorAgent:
    """
    Generates TaskAssignment from merged spec analysis and capped context.
    Used as fallback when the planning pipeline (Backend + Frontend planners) does not produce output.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        assert llm_client is not None, "llm_client is required"
        self.llm = llm_client

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(
        self,
        input_data: TaskGeneratorInput,
        *,
        _split_depth: int = 0,
    ) -> Dict[str, Any]:
        """Generate task plan from merged analysis and capped inputs.

        Returns raw LLM dict (tasks, execution_order, rationale, etc.) for
        the caller to parse.  On JSON parse failures the scope is recursively
        split into microtasks (up to *MAX_MICROTASK_SPLIT_DEPTH* levels).
        If decomposition is exhausted an escalation payload is returned
        (identifiable via the ``_task_generator_escalation`` key).
        """
        try:
            return self._generate(input_data)
        except LLMJsonParseError as exc:
            logger.warning(
                "TaskGenerator: JSON parse failure at depth %d: %s",
                _split_depth, exc,
            )
            return self._decompose_and_retry(
                input_data,
                split_depth=_split_depth,
                parse_error=str(exc),
            )

    # ------------------------------------------------------------------
    # Core generation (no decomposition awareness)
    # ------------------------------------------------------------------

    def _generate(self, input_data: TaskGeneratorInput) -> Dict[str, Any]:
        """Build prompt and call LLM with validation retries.

        Raises ``LLMJsonParseError`` when every attempt produces
        unparseable JSON so the caller can trigger decomposition.
        """
        from tech_lead_agent.prompts import TECH_LEAD_PROMPT

        base_prompt = self._build_prompt(input_data, TECH_LEAD_PROMPT)
        reqs = input_data.requirements
        validation_feedback = ""
        data: Dict[str, Any] = {}

        for attempt in range(MAX_TASK_GENERATOR_RETRIES):
            prompt = base_prompt
            if validation_feedback:
                prompt += "\n\n**VALIDATION FAILED – Fix these issues:**\n" + validation_feedback

            # LLMJsonParseError propagates to run() for decomposition
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

    # ------------------------------------------------------------------
    # Recursive microtask decomposition
    # ------------------------------------------------------------------

    def _decompose_and_retry(
        self,
        input_data: TaskGeneratorInput,
        *,
        split_depth: int,
        parse_error: str,
    ) -> Dict[str, Any]:
        """Split planning scope in half and generate each sub-scope recursively."""
        criteria = list(input_data.requirements.acceptance_criteria or [])

        if split_depth >= MAX_MICROTASK_SPLIT_DEPTH or len(criteria) <= 1:
            logger.error(
                "TaskGenerator: decomposition exhausted at depth %d (%d criteria). "
                "Escalating to Tech Lead.",
                split_depth, len(criteria),
            )
            return self._build_escalation_payload(
                input_data, split_depth, [parse_error],
            )

        mid = max(1, len(criteria) // 2)
        scope_a_criteria = criteria[:mid]
        scope_b_criteria = criteria[mid:]

        logger.info(
            "TaskGenerator: splitting scope at depth %d -> [%d, %d] criteria",
            split_depth, len(scope_a_criteria), len(scope_b_criteria),
        )

        scope_a = self._derive_sub_scope(input_data, scope_a_criteria, split_depth)
        scope_b = self._derive_sub_scope(input_data, scope_b_criteria, split_depth)

        result_a = self.run(scope_a, _split_depth=split_depth + 1)
        result_b = self.run(scope_b, _split_depth=split_depth + 1)

        return self._merge_results(result_a, result_b, input_data, split_depth)

    @staticmethod
    def _derive_sub_scope(
        input_data: TaskGeneratorInput,
        criteria_slice: List[str],
        depth: int,
    ) -> TaskGeneratorInput:
        """Create a narrowed copy of the input with a subset of acceptance criteria."""
        sub_reqs = input_data.requirements.model_copy(
            update={"acceptance_criteria": criteria_slice},
        )
        return input_data.model_copy(update={"requirements": sub_reqs})

    # ------------------------------------------------------------------
    # Merge logic
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_results(
        result_a: Dict[str, Any],
        result_b: Dict[str, Any],
        original_input: TaskGeneratorInput,
        depth: int,
    ) -> Dict[str, Any]:
        """Merge two sub-scope results into one combined assignment.

        Escalation payloads from either branch are propagated: successful
        tasks from the other branch are preserved in the escalation.
        """
        esc_a = result_a.get(ESCALATION_KEY, False)
        esc_b = result_b.get(ESCALATION_KEY, False)

        if esc_a and esc_b:
            failed = (result_a.get("failed_scopes") or []) + (result_b.get("failed_scopes") or [])
            errors = (result_a.get("parse_errors") or []) + (result_b.get("parse_errors") or [])
            tasks = (result_a.get("successful_tasks") or []) + (result_b.get("successful_tasks") or [])
            order = (result_a.get("successful_execution_order") or []) + (result_b.get("successful_execution_order") or [])
            return {
                ESCALATION_KEY: True,
                "failed_scopes": failed,
                "max_depth_reached": max(
                    result_a.get("max_depth_reached", depth),
                    result_b.get("max_depth_reached", depth),
                ),
                "parse_errors": errors,
                "successful_tasks": tasks,
                "successful_execution_order": order,
            }

        def _extract_tasks(r: Dict[str, Any]) -> List[Dict[str, Any]]:
            if r.get(ESCALATION_KEY):
                return r.get("successful_tasks") or []
            return r.get("tasks") or []

        def _extract_order(r: Dict[str, Any]) -> List[str]:
            if r.get(ESCALATION_KEY):
                return r.get("successful_execution_order") or []
            return r.get("execution_order") or []

        def _extract_mapping(r: Dict[str, Any]) -> List[Dict[str, Any]]:
            if r.get(ESCALATION_KEY):
                return []
            return r.get("requirement_task_mapping") or []

        tasks = _extract_tasks(result_a) + _extract_tasks(result_b)
        order = _extract_order(result_a) + _extract_order(result_b)
        mapping = _extract_mapping(result_a) + _extract_mapping(result_b)

        # Deduplicate tasks by id (keep first occurrence)
        seen_ids: set[str] = set()
        deduped_tasks: List[Dict[str, Any]] = []
        for t in tasks:
            tid = t.get("id", "")
            if tid and tid in seen_ids:
                continue
            seen_ids.add(tid)
            deduped_tasks.append(t)

        deduped_order = list(dict.fromkeys(order))

        merged: Dict[str, Any] = {
            "spec_clarification_needed": False,
            "tasks": deduped_tasks,
            "execution_order": deduped_order,
            "rationale": "Merged from microtask decomposition.",
            "summary": f"Merged {len(deduped_tasks)} tasks from split at depth {depth}.",
            "requirement_task_mapping": mapping,
            "clarification_questions": [],
        }

        if esc_a or esc_b:
            escalation_side = result_a if esc_a else result_b
            merged[ESCALATION_KEY] = True
            merged["failed_scopes"] = escalation_side.get("failed_scopes") or []
            merged["max_depth_reached"] = escalation_side.get("max_depth_reached", depth)
            merged["parse_errors"] = escalation_side.get("parse_errors") or []
            merged["successful_tasks"] = deduped_tasks
            merged["successful_execution_order"] = deduped_order

        return merged

    # ------------------------------------------------------------------
    # Escalation payload
    # ------------------------------------------------------------------

    @staticmethod
    def _build_escalation_payload(
        input_data: TaskGeneratorInput,
        depth: int,
        parse_errors: List[str],
    ) -> Dict[str, Any]:
        """Produce a structured payload for the Tech Lead when decomposition is exhausted."""
        return {
            ESCALATION_KEY: True,
            "failed_scopes": [
                {
                    "title": input_data.requirements.title,
                    "acceptance_criteria": list(input_data.requirements.acceptance_criteria or []),
                    "description": input_data.requirements.description[:500],
                }
            ],
            "max_depth_reached": depth,
            "parse_errors": parse_errors[-5:],
            "successful_tasks": [],
            "successful_execution_order": [],
        }

    # ------------------------------------------------------------------
    # Prompt builder (extracted for clarity)
    # ------------------------------------------------------------------

    def _build_prompt(self, input_data: TaskGeneratorInput, tech_lead_prompt: str) -> str:
        """Assemble the full prompt from input data and context limits."""
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

        context_parts: List[str] = [
            TASK_GENERATOR_CONTEXT_NOTE,
            f"**Product Title:** {reqs.title}",
            f"**Description:** {reqs.description}",
            "**Acceptance Criteria:**",
            *[f"- {c}" for c in reqs.acceptance_criteria],
            "**Constraints:**",
            *[f"- {c}" for c in reqs.constraints],
            f"**Priority:** {reqs.priority}",
        ]

        resolved = input_data.resolved_questions or []
        resolved_question_texts = {r.get("question", "") for r in resolved if isinstance(r, dict)}
        remaining_open = [q for q in (input_data.open_questions or []) if q not in resolved_question_texts]

        if resolved:
            context_parts.extend([
                "",
                "**USER-PROVIDED RESOLUTIONS (use these exactly – do NOT override with defaults):**",
                *[f"- **{r.get('question', '')}** -> {r.get('answer', '')} (category: {r.get('category', 'other')})" for r in resolved if isinstance(r, dict)],
            ])
        if remaining_open:
            context_parts.extend([
                "",
                "**OPEN QUESTIONS (resolve with enterprise-informed best-practice defaults; see Step 0 in instructions):**",
                *[f"- {q}" for q in remaining_open],
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
            feedback_lines: List[str] = []
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

        return tech_lead_prompt + "\n\n---\n\n" + "\n".join(context_parts)
