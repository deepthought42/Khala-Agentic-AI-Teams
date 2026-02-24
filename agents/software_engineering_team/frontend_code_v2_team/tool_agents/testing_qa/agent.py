"""Testing/QA tool agent stub for frontend-code-v2."""

from __future__ import annotations

import logging
from ...models import ToolAgentInput, ToolAgentOutput, ToolAgentPhaseInput, ToolAgentPhaseOutput

logger = logging.getLogger(__name__)


class TestingQAToolAgent:
    def run(self, inp: ToolAgentInput) -> ToolAgentOutput:
        return self.execute(inp)

    def execute(self, inp: ToolAgentInput) -> ToolAgentOutput:
        logger.info("Testing/QA stub: microtask %s", inp.microtask.id)
        return ToolAgentOutput(summary="Testing/QA stub — no changes applied.")

    def plan(self, inp: ToolAgentPhaseInput) -> ToolAgentPhaseOutput:
        return ToolAgentPhaseOutput(recommendations=["Include unit and e2e tests in the plan."], summary="Testing/QA planning stub.")

    def review(self, inp: ToolAgentPhaseInput) -> ToolAgentPhaseOutput:
        return ToolAgentPhaseOutput(summary="Testing/QA review stub.")

    def problem_solve(self, inp: ToolAgentPhaseInput) -> ToolAgentPhaseOutput:
        return ToolAgentPhaseOutput(summary="Testing/QA problem-solving stub.")

    def deliver(self, inp: ToolAgentPhaseInput) -> ToolAgentPhaseOutput:
        return ToolAgentPhaseOutput(summary="Testing/QA deliver stub.")
