"""
Containerization adapter stub for the frontend-agent-v2 team.

No code from ``frontend_agent`` is used.
"""

from __future__ import annotations

import logging

from ...models import ToolAgentInput, ToolAgentOutput

logger = logging.getLogger(__name__)


class ContainerizationAdapterAgent:
    """Stub containerization tool agent — extend to delegate to the DevOps team."""

    def run(self, inp: ToolAgentInput) -> ToolAgentOutput:
        logger.info("Containerization stub: microtask %s (not yet implemented)", inp.microtask.id)
        return ToolAgentOutput(
            summary="Containerization adapter stub — no changes applied.",
            recommendations=["Integrate with DevOps Team deployment agents for full support."],
        )
