"""Tests for Code Review agent."""

from unittest.mock import MagicMock

import pytest

from code_review_agent.agent import CodeReviewAgent
from code_review_agent.models import CodeReviewInput, MAX_CODE_REVIEW_CHARS


def test_code_review_agent_truncates_long_code_before_llm_call():
    """When code exceeds MAX_CODE_REVIEW_CHARS, agent truncates so request body stays under limit."""
    long_code = "x" * (MAX_CODE_REVIEW_CHARS + 50_000)
    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = {
        "approved": True,
        "issues": [],
        "summary": "OK",
    }

    agent = CodeReviewAgent(llm_client=mock_llm)
    agent.run(
        CodeReviewInput(
            code=long_code,
            task_description="Test",
            language="typescript",
        )
    )

    mock_llm.complete_json.assert_called_once()
    prompt = mock_llm.complete_json.call_args[0][0]
    # Prompt contains the code; total prompt can exceed cap due to spec/instructions, but code portion must be capped
    assert long_code not in prompt
    assert "x" * (MAX_CODE_REVIEW_CHARS + 1) not in prompt
    assert "... [truncated for code review" in prompt or len(prompt) < len(long_code) + 10_000
