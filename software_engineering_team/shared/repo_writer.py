"""
Repository writer: writes agent outputs to the git repo and commits.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Tuple

from .git_utils import write_files_and_commit

logger = logging.getLogger(__name__)


def _output_to_files_dict(output: Any, subdir: str = "") -> Dict[str, str]:
    """
    Convert agent output to { path: content } dict.
    Handles BackendOutput, FrontendOutput, DevOpsOutput, SecurityOutput, QAOutput.
    """
    prefix = f"{subdir}/" if subdir else ""
    files: Dict[str, str] = {}

    # files dict (Backend, Frontend)
    if hasattr(output, "files") and output.files:
        for path, content in output.files.items():
            files[f"{prefix}{path}"] = content

    # code (Backend, Frontend) - use as main file if no files dict
    if hasattr(output, "code") and output.code and not files:
        lang = getattr(output, "language", "python")
        ext = ".py" if lang == "python" else ".java"
        files[f"{prefix}main{ext}"] = output.code

    # tests (Backend)
    if hasattr(output, "tests") and output.tests:
        files[f"{prefix}tests/test_main.py"] = output.tests

    # DevOps
    if hasattr(output, "pipeline_yaml") and output.pipeline_yaml:
        files[f"{prefix}.github/workflows/ci.yml"] = output.pipeline_yaml
    if hasattr(output, "dockerfile") and output.dockerfile:
        files[f"{prefix}Dockerfile"] = output.dockerfile
    if hasattr(output, "docker_compose") and output.docker_compose:
        files[f"{prefix}docker-compose.yml"] = output.docker_compose
    if hasattr(output, "iac_content") and output.iac_content:
        files[f"{prefix}infrastructure/main.tf"] = output.iac_content
    if hasattr(output, "artifacts") and output.artifacts:
        for path, content in output.artifacts.items():
            files[f"{prefix}{path}"] = content

    # QA/Security fixed_code
    if hasattr(output, "fixed_code") and output.fixed_code:
        files[f"{prefix}fixes.py"] = output.fixed_code

    return files


def write_agent_output(
    repo_path: str | Path,
    output: Any,
    subdir: str = "",
    commit_message: str | None = None,
) -> Tuple[bool, str]:
    """
    Write agent output to repo and commit.

    output: BackendOutput, FrontendOutput, DevOpsOutput, or dict with fixed_code.
    subdir: optional subdirectory (e.g. "backend", "frontend")
    commit_message: override suggested_commit_message if provided.

    Returns (success, message).
    """
    if isinstance(output, dict):
        files = output.get("files", {})
        if output.get("fixed_code"):
            fix_path = output.get("fix_path", "fixes.py")
            files[fix_path] = output["fixed_code"]
        commit_message = commit_message or output.get("commit_message", "chore: apply fixes")
    else:
        files = _output_to_files_dict(output, subdir)
        commit_message = commit_message or getattr(output, "suggested_commit_message", None) or "chore: agent output"

    if not files:
        return False, "No files to write"

    return write_files_and_commit(Path(repo_path).resolve(), files, commit_message)
