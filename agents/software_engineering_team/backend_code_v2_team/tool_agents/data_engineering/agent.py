"""
Data Engineering tool agent: schema design, migrations, data integrity.

Implemented from scratch inside the backend-code-v2 team.
"""

from __future__ import annotations

import logging
from typing import Dict

from shared.llm import LLMClient

from ...models import ToolAgentInput, ToolAgentOutput

logger = logging.getLogger(__name__)

DATA_ENGINEERING_PROMPT = """You are a Data Engineering specialist.

Given a microtask about database schema, migrations, or data integrity,
produce the required files (models, migration scripts, seed data, etc.).

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


class DataEngineeringToolAgent:
    """Produces schema definitions, migration scripts, and data integrity checks."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def run(self, inp: ToolAgentInput) -> ToolAgentOutput:
        prompt = DATA_ENGINEERING_PROMPT.format(
            description=inp.microtask.description or inp.microtask.title,
            language=inp.language,
            existing_code=inp.existing_code[:4000] if inp.existing_code else "(none)",
        )
        logger.info("DataEngineering: running for microtask %s", inp.microtask.id)
        raw = self.llm.complete_json(prompt)
        return ToolAgentOutput(
            files=raw.get("files") or {},
            recommendations=raw.get("recommendations") or [],
            summary=raw.get("summary", ""),
        )
