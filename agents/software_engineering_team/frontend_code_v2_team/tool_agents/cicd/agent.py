"""CI/CD adapter stub for frontend-code-v2."""

from __future__ import annotations

import logging
from ...models import ToolAgentInput, ToolAgentOutput, ToolAgentPhaseInput, ToolAgentPhaseOutput

logger = logging.getLogger(__name__)


class CicdAdapterAgent:
    def run(self, inp: ToolAgentInput) -> ToolAgentOutput:
        return self.execute(inp)

    def execute(self, inp: ToolAgentInput) -> ToolAgentOutput:
        logger.info("CI/CD stub: microtask %s", inp.microtask.id)
        return ToolAgentOutput(summary="CI/CD stub — no changes applied.")

    def plan(self, inp: ToolAgentPhaseInput) -> ToolAgentPhaseOutput:
        return ToolAgentPhaseOutput(recommendations=["Include frontend CI/CD steps in the plan."], summary="CI/CD planning stub.")

    def review(self, inp: ToolAgentPhaseInput) -> ToolAgentPhaseOutput:
        return ToolAgentPhaseOutput(summary="CI/CD review stub.")

    def problem_solve(self, inp: ToolAgentPhaseInput) -> ToolAgentPhaseOutput:
        return ToolAgentPhaseOutput(summary="CI/CD problem-solving stub.")

    def deliver(self, inp: ToolAgentPhaseInput) -> ToolAgentPhaseOutput:
        return ToolAgentPhaseOutput(summary="CI/CD deliver stub.")
