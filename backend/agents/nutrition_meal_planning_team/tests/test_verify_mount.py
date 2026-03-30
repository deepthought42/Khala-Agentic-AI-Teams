"""Verify Nutrition & Meal Planning team is registered in unified API config."""

import sys
from pathlib import Path

# Add backend to path so unified_api can be imported
_backend = Path(__file__).resolve().parent.parent.parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))


def test_team_in_config():
    from unified_api.config import TEAM_CONFIGS

    assert "nutrition_meal_planning" in TEAM_CONFIGS
    config = TEAM_CONFIGS["nutrition_meal_planning"]
    assert config.prefix == "/api/nutrition-meal-planning"
    assert "nutrition" in config.tags or "meal-planning" in config.tags


def test_service_url_env_registered():
    from unified_api.main import TEAM_SERVICE_URL_ENVS

    assert "nutrition_meal_planning" in TEAM_SERVICE_URL_ENVS
    assert TEAM_SERVICE_URL_ENVS["nutrition_meal_planning"] == "NUTRITION_MEAL_PLANNING_SERVICE_URL"
