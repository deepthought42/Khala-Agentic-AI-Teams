"""Execution context for Git LLM tools: repo path and policy flags are host-injected."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GitToolContext:
    """
    Bound to a single job/workspace. The model must never choose ``repo_path``;
    callers construct this from orchestrator state.
    """

    repo_path: Path
    default_base_branch: str = "development"
    allow_merge_to_default_branch: bool = True
    """If False, ``git_merge_branch`` is rejected (read-only / implement-only jobs)."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "repo_path", Path(self.repo_path).resolve())
