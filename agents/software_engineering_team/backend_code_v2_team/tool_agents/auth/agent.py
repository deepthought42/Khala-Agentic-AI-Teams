"""
Authentication and Authorization tool agent: login, RBAC, permissions.

Implemented from scratch inside the backend-code-v2 team.
"""

from __future__ import annotations

import logging

from shared.llm import LLMClient

from ...models import ToolAgentInput, ToolAgentOutput

logger = logging.getLogger(__name__)

AUTH_PROMPT = """You are an Authentication and Authorization specialist.

Given a microtask about login, JWT, RBAC, permission gates, or secure defaults,
produce the required files (auth modules, middleware, permission models, etc.).

**Microtask:** {description}
**Language:** {language}
**Existing code context:** {existing_code}

**Output (JSON):**
{{
  "files": {{ "path/to/file": "content" }},
  "recommendations": ["recommendation 1", ...],
  "summary": "what was produced"
}}

Respond with valid JSON only.
"""


class AuthToolAgent:
    """Produces authentication and authorization code and configurations."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def run(self, inp: ToolAgentInput) -> ToolAgentOutput:
        prompt = AUTH_PROMPT.format(
            description=inp.microtask.description or inp.microtask.title,
            language=inp.language,
            existing_code=inp.existing_code[:4000] if inp.existing_code else "(none)",
        )
        logger.info("Auth: running for microtask %s", inp.microtask.id)
        raw = self.llm.complete_json(prompt)
        return ToolAgentOutput(
            files=raw.get("files") or {},
            recommendations=raw.get("recommendations") or [],
            summary=raw.get("summary", ""),
        )
