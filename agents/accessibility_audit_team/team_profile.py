"""Agency profile helpers for the accessibility audit team.

This module makes the scaffold assets executable by loading the agency blueprint
and validating that orchestrator specialists match the declared roster.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

import yaml


SCAFFOLD_DIR = Path(__file__).parent / "scaffold"
BLUEPRINT_PATH = SCAFFOLD_DIR / "agency_blueprint.yaml"


class AgencyProfileError(RuntimeError):
    """Raised when the agency scaffold profile is invalid."""


def load_agency_blueprint(path: Path = BLUEPRINT_PATH) -> Dict[str, Any]:
    """Load and validate the accessibility agency blueprint asset."""
    if not path.exists():
        raise AgencyProfileError(f"Agency blueprint not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if "agency" not in data or "team" not in data:
        raise AgencyProfileError("Agency blueprint must include 'agency' and 'team' sections")

    return data


def expected_agent_codes(blueprint: Dict[str, Any]) -> Set[str]:
    """Extract all expected agent codes (core + add-ons) from blueprint."""
    team = blueprint.get("team", {})
    leadership = team.get("leadership", [])
    specialists = team.get("specialists", [])
    addons = team.get("addons", [])

    codes: Set[str] = set()
    for section in (leadership, specialists, addons):
        for entry in section:
            code = entry.get("code")
            if code:
                codes.add(code)
    return codes


def validate_agent_roster(
    blueprint: Dict[str, Any],
    implemented_codes: Iterable[str],
) -> List[str]:
    """Return human-readable validation errors for roster mismatches."""
    implemented = set(implemented_codes)
    expected = expected_agent_codes(blueprint)

    missing = sorted(expected - implemented)
    extra = sorted(implemented - expected)

    errors: List[str] = []
    if missing:
        errors.append(f"Missing agents from implementation: {', '.join(missing)}")
    if extra:
        errors.append(f"Implemented agents not in blueprint: {', '.join(extra)}")
    return errors
