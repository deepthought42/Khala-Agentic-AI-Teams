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

    # Uses coordinator when > 30K; may have multiple calls
    assert mock_llm.complete_json.call_count >= 1
    for call in mock_llm.complete_json.call_args_list:
        prompt = call[0][0]
        assert long_code not in prompt
        assert "x" * (MAX_CODE_REVIEW_CHARS + 1) not in prompt


def test_code_review_agent_small_code_uses_single_call():
    """When code <= MAX_CODE_REVIEW_CHARS_SINGLE_CALL, agent uses single LLM call."""
    small_code = "### app/main.py ###\ndef foo(): pass"
    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = {
        "approved": True,
        "issues": [],
        "summary": "OK",
    }

    agent = CodeReviewAgent(llm_client=mock_llm)
    agent.run(
        CodeReviewInput(
            code=small_code,
            task_description="Test",
            language="python",
        )
    )

    mock_llm.complete_json.assert_called_once()
