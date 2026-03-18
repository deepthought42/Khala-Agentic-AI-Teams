"""
Orchestrator for the Agent Builder Team.

Coordinates the multi-phase pipeline:
  1. Process Analyst    → draft flowchart
  2. Flowchart Validator → validate completeness
  3. ── HUMAN CHECKPOINT: approve flowchart ──
  4. Agent Planner       → design agent specs
  5. Plan Reviewer       → review plan quality
  6. ── HUMAN CHECKPOINT: approve plan ──
  7. Agent Builder       → generate team source code
  8. Agent Refiner       → review and correct code
  9. Deliver             → mark job DELIVERED

The orchestrator is called from background threads; it mutates the BuildJob
in-place and persists via the job store after each phase.
"""

from __future__ import annotations

import logging
from typing import Callable

from .agents import (
    AgentBuilderAgent,
    AgentPlannerAgent,
    AgentRefinerAgent,
    FlowchartValidatorAgent,
    PlanReviewerAgent,
    ProcessAnalystAgent,
)
from .models import BuilderPhase, BuildJob

logger = logging.getLogger(__name__)

# Type alias for the save-to-store callback
SaveFn = Callable[[BuildJob], None]


class AgentBuilderOrchestrator:
    """Drives the agent-builder pipeline from DEFINING through DELIVERED."""

    def __init__(self) -> None:
        self.process_analyst = ProcessAnalystAgent()
        self.flowchart_validator = FlowchartValidatorAgent()
        self.agent_planner = AgentPlannerAgent()
        self.plan_reviewer = PlanReviewerAgent()
        self.agent_builder = AgentBuilderAgent()
        self.agent_refiner = AgentRefinerAgent()

    # ------------------------------------------------------------------
    # Phase runners — each called from a background thread
    # ------------------------------------------------------------------

    def run_define_phase(self, job: BuildJob, save: SaveFn) -> None:
        """
        Phase 1: Generate and validate the initial flowchart.
        Transitions: DEFINING → AWAITING_FLOWCHART_APPROVAL (or FAILED).
        """
        logger.info("[job=%s] Starting DEFINING phase.", job.job_id)
        try:
            flowchart = self.process_analyst.analyze(job.process_description)
            flowchart = self.flowchart_validator.validate(flowchart)
            job.flowchart = flowchart
            job.phase = BuilderPhase.AWAITING_FLOWCHART_APPROVAL
            job.touch()
            save(job)
            logger.info("[job=%s] Flowchart ready, awaiting human approval.", job.job_id)
        except Exception as exc:
            self._fail(job, f"Define phase error: {exc}", save)

    def run_planning_phase(self, job: BuildJob, save: SaveFn) -> None:
        """
        Phase 2: Plan the agent team from the approved flowchart.
        Transitions: PLANNING → AWAITING_PLAN_APPROVAL (or FAILED).
        """
        if job.flowchart is None:
            self._fail(job, "Cannot start planning: no flowchart available.", save)
            return

        logger.info("[job=%s] Starting PLANNING phase.", job.job_id)
        try:
            # If the user provided feedback on the flowchart, re-analyze with it
            description = job.process_description
            if job.flowchart_feedback:
                description = f"{description}\n\nAdditional context from reviewer: {job.flowchart_feedback}"

            plan = self.agent_planner.plan(job.flowchart, description)
            plan = self.plan_reviewer.review(plan, job.flowchart)
            job.agent_plan = plan
            job.phase = BuilderPhase.AWAITING_PLAN_APPROVAL
            job.touch()
            save(job)
            logger.info("[job=%s] Agent plan ready, awaiting human approval.", job.job_id)
        except Exception as exc:
            self._fail(job, f"Planning phase error: {exc}", save)

    def run_build_phase(self, job: BuildJob, save: SaveFn) -> None:
        """
        Phase 3: Build and refine the agent team code.
        Transitions: BUILDING → REFINING → DELIVERED (or FAILED).
        """
        if job.agent_plan is None or job.flowchart is None:
            self._fail(job, "Cannot build: no approved plan or flowchart.", save)
            return

        logger.info("[job=%s] Starting BUILD phase.", job.job_id)
        try:
            # Apply any plan feedback to the description context
            description = job.process_description
            if job.plan_feedback:
                description = f"{description}\n\nReviewer feedback on the plan: {job.plan_feedback}"

            files, build_notes = self.agent_builder.build(
                job.agent_plan,
                job.flowchart,
                description,
            )
            job.generated_files = files
            job.phase = BuilderPhase.REFINING
            job.touch()
            save(job)
            logger.info("[job=%s] Initial build complete, starting REFINE phase.", job.job_id)

            # Refine
            refined_files, refinement_notes = self.agent_refiner.refine(files)
            job.generated_files = refined_files
            job.refinement_notes = refinement_notes
            job.delivery_notes = self._compose_delivery_notes(job, build_notes, refinement_notes)
            job.phase = BuilderPhase.DELIVERED
            job.touch()
            save(job)
            logger.info("[job=%s] Build + refinement complete. DELIVERED.", job.job_id)
        except Exception as exc:
            self._fail(job, f"Build phase error: {exc}", save)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fail(job: BuildJob, reason: str, save: SaveFn) -> None:
        logger.error("[job=%s] %s", job.job_id, reason)
        job.phase = BuilderPhase.FAILED
        job.error = reason
        job.touch()
        save(job)

    @staticmethod
    def _compose_delivery_notes(job: BuildJob, build_notes: str, refinement_notes: str) -> str:
        plan = job.agent_plan
        if plan is None:
            return build_notes

        parts = [
            f"## Agent Team: {plan.team_name}",
            "",
            plan.pipeline_description,
            "",
            "### Files generated",
        ]
        for f in job.generated_files:
            parts.append(f"- `{f.filename}` — {f.description or 'see content'}")

        parts += ["", "### Pipeline phases"]
        for phase in plan.phases:
            parts.append(f"- {phase}")

        if plan.human_checkpoints:
            parts += ["", "### Human checkpoints"]
            for cp in plan.human_checkpoints:
                parts.append(f"- {cp}")

        if build_notes:
            parts += ["", "### Build notes", build_notes]

        if refinement_notes and refinement_notes != "No refinements applied.":
            parts += ["", "### Refinement notes", refinement_notes]

        parts += [
            "",
            "### Running the team",
            f"Mount the generated `{plan.team_name}/` directory under `backend/agents/`",
            "then add a `TeamConfig` entry in `unified_api/config.py` and a mount function",
            "in `unified_api/main.py` following the existing pattern.",
        ]

        return "\n".join(parts)
