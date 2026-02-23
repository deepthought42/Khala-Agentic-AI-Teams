"""
API / OpenAPI tool agent: contract design, endpoint implementation, spec validation.

Implemented from scratch inside the frontend-agent-v2 team.
"""

from __future__ import annotations

import logging

from shared.llm import LLMClient

from ...models import ToolAgentInput, ToolAgentOutput

logger = logging.getLogger(__name__)

API_OPENAPI_PROMPT = """You are an API / OpenAPI specialist.

Given a microtask about REST endpoint design, OpenAPI specification, or
service contract work, produce the required files (routers, schemas,
openapi.yaml fragments, etc.).

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


class ApiOpenApiToolAgent:
    """Produces API routes, OpenAPI specs, and service contracts."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def run(self, inp: ToolAgentInput) -> ToolAgentOutput:
        prompt = API_OPENAPI_PROMPT.format(
            description=inp.microtask.description or inp.microtask.title,
            language=inp.language,
            existing_code=inp.existing_code[:4000] if inp.existing_code else "(none)",
        )
        logger.info("ApiOpenApi: running for microtask %s", inp.microtask.id)
        raw = self.llm.complete_json(prompt)
        return ToolAgentOutput(
            files=raw.get("files") or {},
            recommendations=raw.get("recommendations") or [],
            summary=raw.get("summary", ""),
        )
