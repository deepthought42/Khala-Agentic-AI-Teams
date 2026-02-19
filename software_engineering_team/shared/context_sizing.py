"""
Compute max chunk sizes from model context for analysis agents.

Uses chars_per_token ~3.5 (conservative for code/spec text) and reserves
tokens for system prompt, task/spec context, and response.
"""

from __future__ import annotations

from shared.llm import LLMClient


def compute_max_chunk_chars(
    context_tokens: int,
    *,
    reserved_prompt_tokens: int = 6000,
    reserved_response_tokens: int = 4096,
    chars_per_token: float = 3.5,
    min_chars: int = 8000,
) -> int:
    """
    Compute max chars for a single analysis chunk given model context size.

    Args:
        context_tokens: Model's max context (from llm.get_max_context_tokens()).
        reserved_prompt_tokens: Tokens for system prompt, task, spec excerpt, etc.
        reserved_response_tokens: Tokens reserved for LLM response.
        chars_per_token: Conservative chars-per-token (~3.5 for code/spec).
        min_chars: Minimum chunk size (fallback for small models).

    Returns:
        Max chars to use per chunk.
    """
    available_tokens = context_tokens - reserved_prompt_tokens - reserved_response_tokens
    if available_tokens < 512:
        available_tokens = 512  # ensure some room for tiny models
    return max(min_chars, int(available_tokens * chars_per_token))


def compute_code_review_chunk_chars(llm: LLMClient) -> int:
    """
    Max chars per code review chunk. Reserves ~6K for task/spec/arch/existing,
    ~4K for response.
    """
    return compute_max_chunk_chars(
        llm.get_max_context_tokens(),
        reserved_prompt_tokens=6000,
        reserved_response_tokens=4096,
        min_chars=12000,
    )


def compute_spec_chunk_chars(llm: LLMClient) -> int:
    """
    Max chars per spec chunk. Reserves ~2K for requirements header,
    ~4K for response. Kept tight for faster planning.
    """
    return compute_max_chunk_chars(
        llm.get_max_context_tokens(),
        reserved_prompt_tokens=2000,
        reserved_response_tokens=4096,
        min_chars=6000,
    )


def _scale_with_context(llm: LLMClient, base_at_16k: int) -> int:
    """Scale a 16K-context base value by actual model context."""
    ctx = llm.get_max_context_tokens()
    return max(base_at_16k, int(base_at_16k * ctx / 16384))


def compute_code_review_spec_excerpt_chars(llm: LLMClient) -> int:
    """Max chars for spec excerpt in code review (scales with model context)."""
    return _scale_with_context(llm, 8_000)


def compute_code_review_arch_overview_chars(llm: LLMClient) -> int:
    """Max chars for architecture overview in code review (scales with model context)."""
    return _scale_with_context(llm, 2_000)


def compute_code_review_existing_codebase_chars(llm: LLMClient) -> int:
    """Max chars for existing codebase excerpt in code review (scales with model context)."""
    return _scale_with_context(llm, 4_000)


def compute_existing_code_chars(llm: LLMClient) -> int:
    """Max chars for existing codebase when passed to coding agents (spec + code + response)."""
    return compute_max_chunk_chars(
        llm.get_max_context_tokens(),
        reserved_prompt_tokens=8000,
        reserved_response_tokens=8192,
        min_chars=20_000,
    )


def compute_spec_content_chars(llm: LLMClient) -> int:
    """Max chars for spec content in agent prompts."""
    return compute_max_chunk_chars(
        llm.get_max_context_tokens(),
        reserved_prompt_tokens=8000,
        reserved_response_tokens=8192,
        min_chars=15_000,
    )


def compute_spec_excerpt_chars(llm: LLMClient) -> int:
    """Max chars for spec excerpt in refine_task and similar (smaller prompts)."""
    return compute_max_chunk_chars(
        llm.get_max_context_tokens(),
        reserved_prompt_tokens=4000,
        reserved_response_tokens=4096,
        min_chars=8_000,
    )


def compute_build_errors_chars(llm: LLMClient) -> int:
    """Max chars for build/test errors in retry context."""
    return compute_max_chunk_chars(
        llm.get_max_context_tokens(),
        reserved_prompt_tokens=12000,
        reserved_response_tokens=8192,
        min_chars=4_000,
    )


def compute_api_spec_chars(llm: LLMClient) -> int:
    """Max chars for API spec/endpoints in frontend context."""
    return _scale_with_context(llm, 20_000)


def compute_task_generator_spec_chars(llm: LLMClient) -> int:
    """Max chars for spec in Task Generator prompt. Tighter for faster planning."""
    return compute_max_chunk_chars(
        llm.get_max_context_tokens(),
        reserved_prompt_tokens=12000,
        reserved_response_tokens=8192,
        min_chars=12_000,
    )


def compute_task_generator_existing_chars(llm: LLMClient) -> int:
    """Max chars for existing code in Task Generator prompt."""
    return compute_task_generator_spec_chars(llm)


def compute_task_generator_features_chars(llm: LLMClient) -> int:
    """Max chars for features doc in Task Generator prompt. Tighter for faster planning."""
    return _scale_with_context(llm, 6_000)


def compute_task_generator_arch_chars(llm: LLMClient) -> int:
    """Max chars for architecture doc in Task Generator prompt."""
    return _scale_with_context(llm, 5_000)


def compute_spec_outline_chars(llm: LLMClient) -> int:
    """Max chars for spec outline in SpecAnalysisMerger. Tighter for faster planning."""
    return _scale_with_context(llm, 1_500)


def compute_repo_summary_chars(llm: LLMClient) -> int:
    """Max chars for repo state summary in Project Planning."""
    return _scale_with_context(llm, 2_000)


def compute_requirement_mapping_chars(llm: LLMClient) -> int:
    """Max chars for requirement-task mapping in prompts."""
    return _scale_with_context(llm, 2_000)


def compute_code_review_total_chars(llm: LLMClient) -> int:
    """Max total code chars for code review (hard cap to avoid HTTP 400). Kept high but model-aware."""
    return min(150_000, _scale_with_context(llm, 150_000))
