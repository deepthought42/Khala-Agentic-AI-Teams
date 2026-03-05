from accessibility_audit_team.orchestrator import AccessibilityAuditOrchestrator
from accessibility_audit_team.team_profile import (
    expected_agent_codes,
    load_agency_blueprint,
)


def test_blueprint_contains_expected_agents() -> None:
    blueprint = load_agency_blueprint()
    codes = expected_agent_codes(blueprint)
    assert {"APL", "WAS", "MAS", "ATS", "SLMS", "REE", "RA", "QCR"}.issubset(codes)
    assert {"AET", "ARM", "ADSE"}.issubset(codes)


def test_orchestrator_exposes_blueprint_profile() -> None:
    orchestrator = AccessibilityAuditOrchestrator()
    profile = orchestrator.get_agency_profile()
    assert profile["agency"]["codename"] == "IEA"
    assert profile["team"]["leadership"][0]["code"] == "APL"
