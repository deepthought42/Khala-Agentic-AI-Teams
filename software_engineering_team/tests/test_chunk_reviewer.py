"""Tests for Code Review Chunk Reviewer."""

from unittest.mock import MagicMock

import pytest

from code_review_agent.chunk_reviewer import review_chunk


def test_review_chunk_returns_approved_issues_summary():
    """Chunk reviewer returns dict with approved, issues, summary."""
    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = {
        "approved": True,
        "issues": [],
        "summary": "Looks good.",
    }

    result = review_chunk(
        llm=mock_llm,
        code_chunk="### app/main.py ###\ndef foo(): pass",
        file_paths_label="app/main.py",
        task_description="Add endpoint",
        task_requirements="",
        acceptance_criteria=[],
        spec_excerpt="",
        architecture_overview="",
        existing_codebase_excerpt=None,
    )

    assert result["approved"] is True
    assert result["issues"] == []
    assert "Looks good" in result["summary"]
    mock_llm.complete_json.assert_called_once()
    prompt = mock_llm.complete_json.call_args[0][0]
    assert "app/main.py" in prompt
    assert "chunk" in prompt.lower()


def test_review_chunk_includes_file_path_in_issues():
    """Chunk reviewer issues include file_path from response or label."""
    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = {
        "approved": False,
        "issues": [
            {
                "severity": "major",
                "category": "naming",
                "file_path": "app/main.py",
                "description": "Use snake_case",
                "suggestion": "Rename to get_user",
            }
        ],
        "summary": "Fix naming.",
    }

    result = review_chunk(
        llm=mock_llm,
        code_chunk="def GetUser(): pass",
        file_paths_label="app/main.py",
        task_description="Add endpoint",
        task_requirements="",
        acceptance_criteria=[],
        spec_excerpt="",
        architecture_overview="",
        existing_codebase_excerpt=None,
    )

    assert result["approved"] is False
    assert len(result["issues"]) == 1
    assert result["issues"][0]["file_path"] == "app/main.py"
    assert result["issues"][0]["description"] == "Use snake_case"
