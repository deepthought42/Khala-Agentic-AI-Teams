"""OpenAI-compatible tool definitions for Git operations (names match executor dispatch)."""

from __future__ import annotations

from typing import Any, List

# Tool function names must match keys in ``build_git_tool_handlers``.
GIT_TOOL_DEFINITIONS: List[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Show git working tree status (porcelain). Read-only.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Show unstaged and/or staged diffs. Read-only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "staged": {
                        "type": "boolean",
                        "description": "If true, run git diff --cached; else unstaged diff.",
                    },
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional relative paths under the repo to limit the diff.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": "Recent commit history on the current branch (oneline). Read-only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max number of commits (default 20).",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_checkout_branch",
            "description": "Checkout an existing branch in the repo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "branch": {
                        "type": "string",
                        "description": "Branch name (e.g. development, feature/foo).",
                    },
                },
                "required": ["branch"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_create_feature_branch",
            "description": (
                "Create and checkout a feature branch from the base branch (default development). "
                "Pass feature_name without the feature/ prefix (e.g. task-123-api)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "feature_name": {
                        "type": "string",
                        "description": "Slug for the branch; becomes feature/<feature_name>.",
                    },
                    "base_branch": {
                        "type": "string",
                        "description": "Override base branch (defaults to job base branch).",
                    },
                },
                "required": ["feature_name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_write_files_and_commit",
            "description": (
                "Write or update files relative to repo root, git add -A, and commit on the "
                "current branch. Paths must be relative (no ..)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "files": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": "Map of relative path -> full file content.",
                    },
                    "message": {"type": "string", "description": "Commit message."},
                },
                "required": ["files", "message"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit_working_tree",
            "description": "Stage all changes and commit with the given message (no new file content).",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Commit message."},
                },
                "required": ["message"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_merge_branch",
            "description": (
                "Checkout target_branch and merge source_branch into it. "
                "Typically merge a feature branch into development."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source_branch": {"type": "string"},
                    "target_branch": {"type": "string"},
                },
                "required": ["source_branch", "target_branch"],
                "additionalProperties": False,
            },
        },
    },
]
