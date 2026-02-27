"""Shared JSON parsing utilities for planning_v2_team tool agents."""

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from shared.llm import LLMClient

logger = logging.getLogger(__name__)

MAX_DECOMPOSITION_DEPTH = 10
DEFAULT_CHUNK_SIZE = 4000


def parse_json_with_recovery(
    llm: "LLMClient",
    prompt: str,
    agent_name: str = "ToolAgent",
    max_retries: int = 1,
    decompose_fn: Optional[Callable[[str], List[str]]] = None,
    merge_fn: Optional[Callable[[List[Dict[str, Any]]], Dict[str, Any]]] = None,
    original_content: Optional[str] = None,
    chunk_prompt_template: Optional[str] = None,
    _depth: int = 0,
) -> Dict[str, Any]:
    """Parse LLM JSON response with multi-stage recovery.

    Recovery stages:
    1. llm.complete_json() - uses LLMClient's built-in continuation retry
    2. Regex extraction - find {...} in raw response
    3. Explicit continuation request - ask LLM to complete truncated JSON
    4. Decompose into chunks and merge results (recursive)

    Args:
        llm: LLM client for completions
        prompt: The prompt to send to the LLM
        agent_name: Name for logging purposes
        max_retries: Number of retry attempts for the same prompt
        decompose_fn: Optional function to split content into chunks
        merge_fn: Optional function to merge results from chunks
        original_content: The original content being processed (for decomposition)
        chunk_prompt_template: Template for chunk prompts (must have {chunk_content})
        _depth: Internal recursion depth tracker

    Returns:
        Parsed JSON dict, or empty dict if all recovery fails
    """
    last_error: Optional[Exception] = None
    partial_response = ""

    for attempt in range(max_retries + 1):
        try:
            return llm.complete_json(prompt)
        except Exception as e:
            last_error = e
            logger.warning(
                "%s LLM call failed (attempt %d/%d): %s",
                agent_name,
                attempt + 1,
                max_retries + 1,
                str(e)[:200],
            )

            # Extract partial response for continuation attempts
            partial_response = getattr(e, "response_preview", "") or str(e)

            # Stage 2: Try regex extraction from partial response
            extracted = _extract_json_fallback(partial_response)
            if extracted:
                logger.info("%s: Recovered JSON via regex extraction", agent_name)
                return extracted

    # Stage 3: Try explicit continuation request
    if partial_response:
        logger.info("%s: Attempting LLM continuation for truncated response", agent_name)
        continued = _request_continuation(llm, prompt, partial_response, agent_name)
        if continued:
            return continued

    # Stage 4: Decompose into chunks if possible
    if (
        decompose_fn is not None
        and merge_fn is not None
        and original_content
        and _depth < MAX_DECOMPOSITION_DEPTH
    ):
        logger.info(
            "%s: Decomposing content into chunks (depth %d)", agent_name, _depth + 1
        )
        chunks = decompose_fn(original_content)

        if len(chunks) > 1:
            results: List[Dict[str, Any]] = []
            for i, chunk in enumerate(chunks):
                logger.debug(
                    "%s: Processing chunk %d/%d (%d chars)",
                    agent_name,
                    i + 1,
                    len(chunks),
                    len(chunk),
                )

                # Use chunk prompt template if provided, otherwise use a generic one
                if chunk_prompt_template:
                    chunk_prompt = chunk_prompt_template.format(chunk_content=chunk)
                else:
                    chunk_prompt = _create_generic_chunk_prompt(prompt, chunk)

                # Recursively process each chunk
                chunk_result = parse_json_with_recovery(
                    llm=llm,
                    prompt=chunk_prompt,
                    agent_name=f"{agent_name}_chunk{i + 1}",
                    max_retries=max_retries,
                    decompose_fn=decompose_fn,
                    merge_fn=merge_fn,
                    original_content=chunk,
                    chunk_prompt_template=chunk_prompt_template,
                    _depth=_depth + 1,
                )
                if chunk_result:
                    results.append(chunk_result)

            if results:
                merged = merge_fn(results)
                logger.info(
                    "%s: Merged %d chunk results successfully", agent_name, len(results)
                )
                return merged

    logger.error("%s: All JSON recovery attempts failed: %s", agent_name, last_error)
    return {}


def _request_continuation(
    llm: "LLMClient",
    original_prompt: str,
    partial_response: str,
    agent_name: str,
) -> Dict[str, Any]:
    """Request LLM to continue from a truncated JSON response.

    Returns parsed JSON if successful, empty dict otherwise.
    """
    # Clean up partial response - extract just the JSON part
    json_start = partial_response.find("{")
    if json_start == -1:
        return {}

    partial_json = partial_response[json_start:]

    continuation_prompt = (
        "The previous JSON response was truncated. Here is what was generated so far:\n\n"
        f"```json\n{partial_json}\n```\n\n"
        "Continue from where it stopped. Output ONLY the remainder of the JSON "
        "so that when appended to the previous output it completes the object. "
        "Do not repeat any content. No explanation, just the missing JSON."
    )

    try:
        continuation = llm.complete_text(continuation_prompt)
        if not continuation:
            return {}

        # Merge the partial and continuation
        merged = partial_json.rstrip() + "\n" + continuation.lstrip()

        # Try to parse the merged result
        extracted = _extract_json_fallback(merged)
        if extracted:
            logger.info("%s: Successfully recovered JSON via continuation", agent_name)
            return extracted

        # Try direct parse
        try:
            return json.loads(merged)
        except json.JSONDecodeError:
            pass

    except Exception as e:
        logger.warning("%s: Continuation request failed: %s", agent_name, e)

    return {}


def _extract_json_fallback(raw: str) -> Dict[str, Any]:
    """Extract JSON object from raw text using regex and repair strategies."""
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        json_str = match.group()

        # Try direct parse
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

        # Try cleaning trailing commas
        cleaned = re.sub(r",\s*([}\]])", r"\1", json_str)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Try truncating to valid JSON
        truncated = _truncate_to_valid_json(cleaned)
        if truncated:
            try:
                return json.loads(truncated)
            except json.JSONDecodeError:
                pass

    return {}


def _truncate_to_valid_json(json_str: str) -> str:
    """Try to truncate a malformed JSON string to make it valid.

    Useful for responses that were cut off mid-stream.
    """
    # Find where arrays/objects might have been truncated
    for end_char in ["}]}", "]}", "}", "]"]:
        idx = json_str.rfind(end_char[0])
        if idx > 0:
            candidate = json_str[: idx + 1]
            # Count braces/brackets to see if we can close them
            open_braces = candidate.count("{") - candidate.count("}")
            open_brackets = candidate.count("[") - candidate.count("]")
            if open_braces >= 0 and open_brackets >= 0:
                # Add missing closing characters
                candidate += "]" * open_brackets + "}" * open_braces
                return candidate
    return ""


def _create_generic_chunk_prompt(original_prompt: str, chunk: str) -> str:
    """Create a generic chunk prompt based on the original prompt."""
    # Extract the JSON schema hint from the original prompt if present
    schema_match = re.search(r"(\{[^}]*\"[^\"]+\"[^}]*\})", original_prompt)
    schema_hint = schema_match.group(1) if schema_match else ""

    return f"""Process this portion of the content and return JSON with the same structure.

CONTENT CHUNK:
---
{chunk}
---

{f"Expected JSON structure: {schema_hint}" if schema_hint else "Return JSON with the relevant fields found in this chunk."}

Keep your response concise. Only include findings from THIS chunk.
"""


def default_decompose_by_sections(content: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> List[str]:
    """Split content into sections by markdown headers or fixed-size chunks.

    First tries to split by ## headers. If that produces only one section,
    falls back to fixed-size chunking.
    """
    # Try splitting by ## headers
    sections = re.split(r"\n(?=## )", content)
    if len(sections) > 1:
        return [s.strip() for s in sections if s.strip()]

    # Try splitting by # headers
    sections = re.split(r"\n(?=# )", content)
    if len(sections) > 1:
        return [s.strip() for s in sections if s.strip()]

    # Fall back to fixed-size chunks
    chunks = []
    for i in range(0, len(content), chunk_size):
        chunk = content[i : i + chunk_size]
        if chunk.strip():
            chunks.append(chunk)
    return chunks if chunks else [content]


def default_merge_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge results by concatenating list fields and taking first scalar fields.

    This is a generic merge that works for most JSON structures where:
    - Lists should be concatenated
    - Scalars (strings, numbers, bools) take the first non-empty value
    - Nested dicts are merged recursively
    """
    if not results:
        return {}

    merged: Dict[str, Any] = {}

    for result in results:
        for key, value in result.items():
            if key not in merged:
                merged[key] = value
            elif isinstance(value, list) and isinstance(merged[key], list):
                # Concatenate lists
                merged[key].extend(value)
            elif isinstance(value, dict) and isinstance(merged[key], dict):
                # Recursively merge dicts
                for k, v in value.items():
                    if k not in merged[key]:
                        merged[key][k] = v
                    elif isinstance(v, list) and isinstance(merged[key][k], list):
                        merged[key][k].extend(v)
            # For scalars, keep the first non-empty value
            elif not merged[key] and value:
                merged[key] = value

    return merged
