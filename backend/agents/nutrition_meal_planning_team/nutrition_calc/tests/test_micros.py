"""SPEC-003 §6.1 — DRI lookup for every (sex × age-band) combination v1 ships."""

from __future__ import annotations

import pytest

from nutrition_meal_planning_team.models import ReproductiveState, Sex
from nutrition_meal_planning_team.nutrition_calc.micros import (
    V1_MICRO_NUTRIENTS,
    age_band_for,
    compute_micros,
)
from nutrition_meal_planning_team.nutrition_calc.rationale import RationaleBuilder


@pytest.mark.parametrize(
    "age,expected_band",
    [
        (19, "19_30"),
        (30, "19_30"),
        (31, "31_50"),
        (50, "31_50"),
        (51, "51_70"),
        (70, "51_70"),
        (71, "71_plus"),
        (90, "71_plus"),
    ],
)
def test_age_band_mapping(age, expected_band):
    assert age_band_for(age) == expected_band


def test_adult_female_full_micros_populated():
    r = RationaleBuilder()
    m = compute_micros(
        sex=Sex.female,
        age_years=32,
        reproductive_state=ReproductiveState.none,
        rationale=r,
    )
    for nutrient in V1_MICRO_NUTRIENTS:
        assert nutrient in m, f"missing {nutrient}"
    # Spot-check values.
    assert m["fiber_g"].target == 25
    assert m["sodium_mg"].upper == 2300
    assert m["iron_mg"].target == 18
    assert m["calcium_mg"].target == 1000


def test_adult_male_iron_lower_than_female():
    r = RationaleBuilder()
    female = compute_micros(
        sex=Sex.female,
        age_years=30,
        reproductive_state=ReproductiveState.none,
        rationale=r,
    )
    r2 = RationaleBuilder()
    male = compute_micros(
        sex=Sex.male,
        age_years=30,
        reproductive_state=ReproductiveState.none,
        rationale=r2,
    )
    assert male["iron_mg"].target < female["iron_mg"].target


def test_age_71_plus_calcium_raised_for_male():
    """Male 71+ calcium bumps from 1000 → 1200."""
    r = RationaleBuilder()
    m = compute_micros(
        sex=Sex.male,
        age_years=75,
        reproductive_state=ReproductiveState.none,
        rationale=r,
    )
    assert m["calcium_mg"].target == 1200


def test_pregnant_t2_adds_fiber_and_iron():
    """Reproductive-state deltas applied by micros lookup."""
    r = RationaleBuilder()
    m = compute_micros(
        sex=Sex.female,
        age_years=30,
        reproductive_state=ReproductiveState.pregnant_t2,
        rationale=r,
    )
    # Base fiber 25 + delta 3 = 28
    assert m["fiber_g"].target == 28
    # Iron 18 + 9 = 27
    assert m["iron_mg"].target == 27
