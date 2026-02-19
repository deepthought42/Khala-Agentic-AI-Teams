"""Chunk Reviewer: reviews one chunk of code (used by CodeReviewCoordinator)."""

from __future__ import annotations

import logging
from typing import List, Optional

from shared.llm import LLMClient

from .models import (
    ChunkReviewInput,
    ChunkReviewOutput,
    MAX_ARCH_OVERVIEW_CHARS,
    MAX_CHARS_PER_CHUNK,
    MAX_EXISTING_CODEBASE_EXCERPT_CHARS,
    MAX_SPEC_EXCERPT_CHARS,
)
from .prompts import CODE_REVIEW_PROMPT

logger = logging.getLogger(__name__)

CHUNK_REVIEW_NOTE = "\n**Note:** This is one chunk of the full codebase. Review only the code below. Report issues with file_path set to the path provided for this chunk.\n"


def _truncate(s: str, max_chars: int) -> str:
    if not s or len(s) <= max_chars:
        return s or ""
    return s[:max_chars] + "\n\n... [truncated]"


class ChunkReviewAgent:
    """Reviews one chunk of code. Used by CodeReviewCoordinator for large codebases."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def run(self, input_data: ChunkReviewInput) -> ChunkReviewOutput:
        """Review one chunk and return approved, issues, summary."""
        result = _run_chunk_review(self.llm, input_data)
        return ChunkReviewOutput(
            approved=result["approved"],
            issues=result["issues"],
            summary=result["summary"],
        )


def _run_chunk_review(llm: LLMClient, input_data: ChunkReviewInput) -> dict:
    """
    Review one chunk of code. Returns dict with approved, issues, summary.
    """
    code_chunk = _truncate(input_data.code_chunk, MAX_CHARS_PER_CHUNK)
    spec_excerpt = _truncate(input_data.spec_excerpt, MAX_SPEC_EXCERPT_CHARS)
    architecture_overview = _truncate(input_data.architecture_overview, MAX_ARCH_OVERVIEW_CHARS)
    existing_codebase_excerpt = _truncate(
        input_data.existing_codebase_excerpt or "", MAX_EXISTING_CODEBASE_EXCERPT_CHARS
    )

    context_parts = [
        CHUNK_REVIEW_NOTE,
        f"**Files in this chunk:** {input_data.file_path_or_label}",
        f"**Language:** python" if "def " in code_chunk[:500] else "**Language:** typescript",
        f"**Task description:** {input_data.task_description}",
    ]
    if input_data.task_requirements:
        context_parts.extend(["", f"**Task requirements:**", input_data.task_requirements])
    if input_data.acceptance_criteria:
        context_parts.extend([
            "",
            "**Acceptance criteria (code MUST meet all of these):**",
            *[f"- {c}" for c in input_data.acceptance_criteria],
        ])
    if spec_excerpt:
        context_parts.extend([
            "",
            "**Project specification (excerpt):**",
            "---",
            spec_excerpt,
            "---",
        ])
    if architecture_overview:
        context_parts.extend(["", "**Architecture:**", architecture_overview])
    if existing_codebase_excerpt:
        context_parts.extend([
            "",
            "**Existing codebase (excerpt):**",
            "---",
            existing_codebase_excerpt,
            "---",
        ])
    context_parts.extend([
        "",
        "**Code to review:**",
        "```",
        code_chunk,
        "```",
    ])

    prompt = CODE_REVIEW_PROMPT + "\n\n---\n\n" + "\n".join(context_parts)
    data = llm.complete_json(prompt, temperature=0.1)

    issues = []
    for issue_data in data.get("issues") or []:
        if isinstance(issue_data, dict) and issue_data.get("description"):
            fp = issue_data.get("file_path") or input_data.file_path_or_label
            issues.append({
                "severity": issue_data.get("severity", "major"),
                "category": issue_data.get("category", "general"),
                "file_path": fp,
                "description": issue_data.get("description", ""),
                "suggestion": issue_data.get("suggestion", ""),
            })

    return {
        "approved": bool(data.get("approved", False)),
        "issues": issues,
        "summary": str(data.get("summary", "")),
    }
