"""
Data Engineering tool agent: schema design, migrations, data integrity.

Implemented from scratch inside the backend-code-v2 team.
Uses template-based output (not JSON) so parsing works across model providers.
"""

from __future__ import annotations

import logging

from shared.llm import LLMClient

from ...models import ToolAgentInput, ToolAgentOutput
from ...output_templates import parse_files_and_summary_template
from ...prompts import FILES_OUTPUT_TEMPLATE_INSTRUCTIONS

logger = logging.getLogger(__name__)

DATA_ENGINEERING_PROMPT = """You are a Data Engineering specialist.

Given a microtask about database schema, migrations, or data integrity,
produce the required files (models, migration scripts, seed data, etc.).

**Microtask:** {description}
**Language:** {language}
**Existing code context:** {existing_code}
""" + FILES_OUTPUT_TEMPLATE_INSTRUCTIONS


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
        raw = self.llm.complete_text(prompt)
        data = parse_files_and_summary_template(raw)
        return ToolAgentOutput(
            files=data.get("files") or {},
            recommendations=[],
            summary=data.get("summary", ""),
        )
