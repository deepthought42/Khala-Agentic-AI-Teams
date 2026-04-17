"""SPEC-003 §6.1 — PAL multipliers and TDEE."""

from __future__ import annotations

import pytest

from nutrition_meal_planning_team.models import ActivityLevel
from nutrition_meal_planning_team.nutrition_calc.rationale import RationaleBuilder
from nutrition_meal_planning_team.nutrition_calc.tdee import compute_tdee


@pytest.mark.parametrize(
    "level,pal",
    [
        (ActivityLevel.sedentary, 1.2),
        (ActivityLevel.light, 1.375),
        (ActivityLevel.moderate, 1.55),
        (ActivityLevel.active, 1.725),
        (ActivityLevel.very_active, 1.9),
    ],
)
def test_tdee_multiplier_exact(level, pal):
    r = RationaleBuilder()
    tdee = compute_tdee(bmr_kcal=1500.0, activity_level=level, rationale=r)
    assert tdee == pytest.approx(1500.0 * pal)


def test_tdee_rationale_contains_pal_and_bmr():
    r = RationaleBuilder()
    compute_tdee(bmr_kcal=1500, activity_level=ActivityLevel.moderate, rationale=r)
    step = r.build(cohort="general_adult").steps[0]
    assert step.id == "tdee_bmr_times_pal"
    assert step.inputs["bmr_kcal"] == 1500
    assert step.inputs["pal"] == 1.55
