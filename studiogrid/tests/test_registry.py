from pathlib import Path

from studiogrid.runtime.registry_loader import RegistryLoader


def _loader() -> RegistryLoader:
    return RegistryLoader(Path(__file__).resolve().parents[1] / "src" / "studiogrid")


def test_list_agents_returns_metadata():
    agents = _loader().list_agents()
    assert any(agent["agent_id"] == "design_lead" for agent in agents)
    assert any("skills" in agent for agent in agents)


def test_find_assisting_agents_prefers_same_team():
    loader = _loader()
    result = loader.find_assisting_agents(
        problem_description="Need accessibility review and QA on interface updates",
        required_skills=["accessibility_review"],
        requesting_agent_id="design_lead",
        limit=3,
    )

    assert result["matches"]
    assert result["matches"][0]["agent_id"] in {"design_lead", "qa_specialist"}
    assert result["matches"][0]["is_same_team"] is True


def test_list_teams_available_only_filters_unavailable():
    teams = _loader().list_teams(available_only=True)
    assert teams
    assert all(team["availability"] == "available" for team in teams)
