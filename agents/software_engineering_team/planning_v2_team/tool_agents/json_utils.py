"""Shared JSON parsing utilities for planning_v2_team tool agents."""

import json
import logging
import re
from typing import Any, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from shared.llm import LLMClient

logger = logging.getLogger(__name__)


def parse_json_with_recovery(
    llm: "LLMClient",
    prompt: str,
    agent_name: str = "ToolAgent",
    max_retries: int = 1,
) -> Dict[str, Any]:
    """Parse LLM JSON response with multi-stage recovery.

    Recovery stages:
    1. llm.complete_json() - uses LLMClient's built-in continuation retry
    2. Regex extraction - find {...} in raw response
    3. Retry with simplified prompt (if max_retries > 0)
    """
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return llm.complete_json(prompt)
        except Exception as e:
            last_error = e
            logger.warning("%s LLM call failed (attempt %d): %s", agent_name, attempt + 1, e)

            raw_preview = getattr(e, "response_preview", "") or str(e)
            extracted = _extract_json_fallback(raw_preview)
            if extracted:
                logger.info("%s: Recovered JSON via regex extraction", agent_name)
                return extracted

    logger.error("%s: All JSON recovery attempts failed: %s", agent_name, last_error)
    return {}


def _extract_json_fallback(raw: str) -> Dict[str, Any]:
    """Extract JSON object from raw text using regex."""
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            cleaned = re.sub(r",\s*([}\]])", r"\1", match.group())
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass
    return {}
