"""SPEC-003 §6.1 — energy-target math + safety floor."""

from __future__ import annotations

import pytest

from nutrition_meal_planning_team.models import GoalsInfo
from nutrition_meal_planning_team.nutrition_calc.energy_goal import (
    ABSOLUTE_KCAL_FLOOR,
    KCAL_PER_KG_FAT,
    compute_energy_target,
)
from nutrition_meal_planning_team.nutrition_calc.rationale import RationaleBuilder


def _rb():
    return RationaleBuilder()


def test_maintain_equals_tdee():
    r = _rb()
    t = compute_energy_target(
        tdee_kcal=2200,
        bmr_kcal=1500,
        goals=GoalsInfo(goal_type="maintain"),
        weight_kg=70,
        rationale=r,
    )
    assert t == 2200


def test_lose_weight_applies_deficit():
    r = _rb()
    # 0.45 kg/wk → 7700·0.45/7 = 495 kcal/day deficit
    t = compute_energy_target(
        tdee_kcal=2200,
        bmr_kcal=1500,
        goals=GoalsInfo(goal_type="lose_weight", rate_kg_per_week=0.45),
        weight_kg=70,
        rationale=r,
    )
    assert t == pytest.approx(2200 - 495)


def test_gain_weight_applies_surplus():
    r = _rb()
    t = compute_energy_target(
        tdee_kcal=2200,
        bmr_kcal=1500,
        goals=GoalsInfo(goal_type="gain_weight", rate_kg_per_week=0.25),
        weight_kg=70,
        rationale=r,
    )
    assert t == pytest.approx(2200 + KCAL_PER_KG_FAT * 0.25 / 7)


def test_muscle_adds_small_surplus():
    r = _rb()
    t = compute_energy_target(
        tdee_kcal=2200,
        bmr_kcal=1500,
        goals=GoalsInfo(goal_type="muscle"),
        weight_kg=70,
        rationale=r,
    )
    assert t == 2450


def test_rate_cap_one_percent_of_body_weight():
    """Requested rate >1% body weight/week is reduced."""
    r = _rb()
    # 60 kg person asking for 1.0 kg/wk -> capped at 0.6.
    t = compute_energy_target(
        tdee_kcal=2200,
        bmr_kcal=1500,
        goals=GoalsInfo(goal_type="lose_weight", rate_kg_per_week=1.0),
        weight_kg=60,
        rationale=r,
    )
    built = r.build(cohort="general_adult")
    ids = [s.id for s in built.steps]
    assert "rate_capped_by_body_weight" in ids
    # 0.6 kg/wk cap -> 7700·0.6/7 = 660 kcal/day deficit
    assert t == pytest.approx(2200 - 660, abs=0.5)


def test_safety_floor_absolute_1200():
    """kcal target is clamped to max(1200, 0.8·BMR)."""
    r = _rb()
    # Huge deficit pushes target below floor.
    t = compute_energy_target(
        tdee_kcal=1500,
        bmr_kcal=1300,
        goals=GoalsInfo(goal_type="lose_weight", rate_kg_per_week=0.9),
        weight_kg=100,
        rationale=r,
    )
    # floor = max(1200, 0.8·1300) = 1200 (1040 < 1200)
    assert t == ABSOLUTE_KCAL_FLOOR
    ids = [s.id for s in r.build(cohort="general_adult").steps]
    assert "safety_floor_applied" in ids


def test_safety_floor_bmr_based():
    """Floor follows 0.8·BMR when BMR is high enough."""
    r = _rb()
    # 0.8 × 1800 = 1440 > 1200 → BMR-based floor.
    t = compute_energy_target(
        tdee_kcal=2500,
        bmr_kcal=1800,
        goals=GoalsInfo(goal_type="lose_weight", rate_kg_per_week=1.0),
        weight_kg=120,
        rationale=r,
    )
    # 1% of 120 = 1.2 but SPEC-002 caps input at 1.0; effective rate 1.0.
    # deficit = 7700/7 ≈ 1100; target = 2500 − 1100 = 1400, below 1440 floor.
    assert t == pytest.approx(1440, abs=0.5)
