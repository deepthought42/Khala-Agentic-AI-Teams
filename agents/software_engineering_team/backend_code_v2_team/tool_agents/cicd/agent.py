"""
CI/CD adapter stub for the backend-code-v2 team.

This is a thin adapter that can be extended to call DevOps Team APIs.
No code from ``backend_agent`` is used.
"""

from __future__ import annotations

import logging

from ...models import ToolAgentInput, ToolAgentOutput

logger = logging.getLogger(__name__)


class CicdAdapterAgent:
    """Stub CI/CD tool agent — extend to delegate to the DevOps team."""

    def run(self, inp: ToolAgentInput) -> ToolAgentOutput:
        logger.info("CI/CD stub: microtask %s (not yet implemented)", inp.microtask.id)
        return ToolAgentOutput(
            summary="CI/CD adapter stub — no changes applied.",
            recommendations=["Integrate with DevOps Team CI/CD agents for full support."],
        )
