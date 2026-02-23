"""
Deliver phase: write files, commit, and merge to development.

Uses only ``shared.git_utils`` — no code from ``frontend_agent``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, Optional

from shared.git_utils import (
    DEVELOPMENT_BRANCH,
    abort_merge,
    branch_has_commits_ahead_of,
    checkout_branch,
    create_feature_branch,
    delete_branch,
    merge_branch,
)
from shared.repo_writer import write_agent_output, NO_FILES_TO_WRITE_MSG

from ..models import DeliverResult
from ..prompts import DELIVER_COMMIT_MSG_TEMPLATE

logger = logging.getLogger(__name__)


class _FilesPayload:
    """Minimal duck-type wrapper so ``write_agent_output`` can consume it."""

    def __init__(self, files: Dict[str, str], summary: str, commit_msg: str) -> None:
        self.files = files
        self.summary = summary
        self.suggested_commit_message = commit_msg
        self.gitignore_entries: list[str] = []


def run_deliver(
    *,
    task_id: str,
    repo_path: Path,
    files: Dict[str, str],
    summary: str,
    task_title: str = "",
) -> DeliverResult:
    """
    Create feature branch, write files, commit, merge to development.

    If the feature branch already exists it is recreated from development.
    """
    result = DeliverResult()

    if not files:
        result.summary = "No files to deliver."
        return result

    # 1. Create feature branch
    slug = re.sub(r"[^a-z0-9-]+", "-", (task_title or task_id).lower()).strip("-")[:40] or "task"
    ok, branch_msg = create_feature_branch(repo_path, DEVELOPMENT_BRANCH, f"{task_id}-{slug}")
    if not ok:
        result.summary = f"Feature branch creation failed: {branch_msg}"
        logger.error("[%s] Deliver: %s", task_id, result.summary)
        checkout_branch(repo_path, DEVELOPMENT_BRANCH)
        return result
    result.branch_name = branch_msg or f"feature/{task_id}-{slug}"

    # 2. Write files and commit
    scope = slug[:20]
    commit_msg = DELIVER_COMMIT_MSG_TEMPLATE.format(scope=scope, summary=summary[:72])
    payload = _FilesPayload(files, summary, commit_msg)
    write_ok, write_msg = write_agent_output(repo_path, payload, subdir="")
    if not write_ok:
        result.summary = f"Write failed: {write_msg}"
        logger.error("[%s] Deliver: %s", task_id, result.summary)
        checkout_branch(repo_path, DEVELOPMENT_BRANCH)
        return result
    result.commit_messages.append(commit_msg)

    # 3. Merge to development
    merge_ok, merge_msg = merge_branch(repo_path, result.branch_name, DEVELOPMENT_BRANCH)
    if not merge_ok:
        result.summary = f"Merge failed: {merge_msg}"
        logger.error("[%s] Deliver: %s", task_id, result.summary)
        abort_merge(repo_path)
        checkout_branch(repo_path, DEVELOPMENT_BRANCH)
        return result

    result.merged = True

    # 4. Cleanup feature branch
    delete_branch(repo_path, result.branch_name)
    checkout_branch(repo_path, DEVELOPMENT_BRANCH)

    result.summary = f"Merged {result.branch_name} → {DEVELOPMENT_BRANCH}."
    logger.info("[%s] Deliver: %s", task_id, result.summary)
    return result
