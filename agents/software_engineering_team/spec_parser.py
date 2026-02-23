"""
Parse initial_spec.md into ProductRequirements for the software engineering team.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from shared.models import ProductRequirements

logger = logging.getLogger(__name__)

SPEC_FILENAME = "initial_spec.md"

ENV_WORKSPACE_ROOT = "WORKSPACE_ROOT"


def parse_spec_with_llm(spec_content: str, llm_client) -> ProductRequirements:
    """
    Use LLM to extract structured ProductRequirements from spec content.
    """
    logger.info("Parsing spec with LLM (%s chars)", len(spec_content))
    prompt = """Parse the following software project specification into a structured format.

Return a single JSON object with:
- "title": string (project/feature name)
- "description": string (full description)
- "acceptance_criteria": list of strings (must-have requirements)
- "constraints": list of strings (technical/business constraints)
- "priority": string ("high", "medium", or "low")

Specification:
---
"""
    prompt += spec_content
    prompt += "\n---\n\nRespond with valid JSON only. No explanatory text."

    data = llm_client.complete_json(prompt, temperature=0.1)
    if not isinstance(data.get("acceptance_criteria"), list):
        raise ValueError(
            f"LLM returned invalid spec structure: 'acceptance_criteria' must be a list, got {type(data.get('acceptance_criteria'))}"
        )
    if not isinstance(data.get("constraints"), list):
        raise ValueError(
            f"LLM returned invalid spec structure: 'constraints' must be a list, got {type(data.get('constraints'))}"
        )
    reqs = ProductRequirements(
        title=data.get("title") or "Software Project",
        description=data.get("description") or spec_content[:2000],
        acceptance_criteria=data["acceptance_criteria"],
        constraints=data["constraints"],
        priority=data.get("priority") or "medium",
        metadata={"parsed_from": "initial_spec.md"},
    )
    logger.info("Parsed spec: title=%s, %s acceptance criteria", reqs.title, len(reqs.acceptance_criteria))
    return reqs


def load_spec_from_repo(repo_path: str | Path) -> str:
    """
    Load initial_spec.md from the root of the given path.
    Raises FileNotFoundError if not found.
    """
    path = Path(repo_path).resolve()
    spec_file = path / SPEC_FILENAME
    if not spec_file.exists():
        raise FileNotFoundError(f"{SPEC_FILENAME} not found at {spec_file}")
    return spec_file.read_text()


def _check_workspace_containment(path: Path) -> None:
    """Reject *path* if it escapes the configured workspace root.

    When ``WORKSPACE_ROOT`` is set, *path* (already resolved) must be equal to
    or a sub-directory of the workspace root.  This prevents path-traversal
    attacks where a caller supplies ``../../sensitive``.

    If ``WORKSPACE_ROOT`` is **not** set the check is a no-op so existing
    development workflows are unaffected.
    """
    workspace_root_str = os.environ.get(ENV_WORKSPACE_ROOT)
    if not workspace_root_str:
        return
    workspace_root = Path(workspace_root_str).resolve()
    try:
        path.relative_to(workspace_root)
    except ValueError:
        raise ValueError(
            f"Path {path} is outside the allowed workspace root ({workspace_root})"
        )


def validate_work_path(work_path: str | Path) -> Path:
    """
    Validate that the path exists, is a directory, and has initial_spec.md.
    Does not require the path to be a git repository.
    When WORKSPACE_ROOT is set, also verifies the path does not escape the
    workspace root (path-traversal protection).
    Returns the resolved Path. Raises ValueError on failure.
    """
    path = Path(work_path).resolve()
    _check_workspace_containment(path)
    if not path.exists():
        raise ValueError(f"Path does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"Path is not a directory: {path}")
    spec_file = path / SPEC_FILENAME
    if not spec_file.exists():
        raise ValueError(f"{SPEC_FILENAME} not found at {spec_file}")
    return path


def validate_repo_path(repo_path: str | Path) -> Path:
    """
    Validate that the path exists, is a directory, is a git repo, and has initial_spec.md.
    When WORKSPACE_ROOT is set, also verifies the path does not escape the
    workspace root (path-traversal protection).
    Returns the resolved Path. Raises ValueError on failure.
    """
    path = Path(repo_path).resolve()
    _check_workspace_containment(path)
    if not path.exists():
        raise ValueError(f"Path does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"Path is not a directory: {path}")
    if not (path / ".git").exists():
        raise ValueError(f"Path is not a git repository (no .git): {path}")
    spec_file = path / SPEC_FILENAME
    if not spec_file.exists():
        raise ValueError(f"{SPEC_FILENAME} not found in repo root at {spec_file}")
    return path
