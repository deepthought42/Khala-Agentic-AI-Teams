"""SPEC-003 §6.1 — macro allocation + AMDR clamps."""

from __future__ import annotations

import pytest

from nutrition_meal_planning_team.models import GoalsInfo
from nutrition_meal_planning_team.nutrition_calc.macros import (
    KCAL_PER_G_CARBS,
    KCAL_PER_G_FAT,
    KCAL_PER_G_PROTEIN,
    compute_macros,
)
from nutrition_meal_planning_team.nutrition_calc.rationale import RationaleBuilder


def _sum_matches_kcal(macros, kcal_target):
    total = (
        macros.protein_g * KCAL_PER_G_PROTEIN
        + macros.fat_g * KCAL_PER_G_FAT
        + macros.carbs_g * KCAL_PER_G_CARBS
    )
    return total == pytest.approx(kcal_target, abs=1.0)


def test_lose_weight_protein_at_goal_gpk():
    r = RationaleBuilder()
    m = compute_macros(
        kcal_target=1600,
        weight_kg=64,
        goals=GoalsInfo(goal_type="lose_weight"),
        dietary_needs=[],
        rationale=r,
    )
    # 1.6 g/kg × 64 = 102.4 g; within AMDR (10-35%).
    assert m.protein_g == pytest.approx(102.4, abs=0.5)
    # Fat default = 25% of kcal = 400 kcal = 44.4 g.
    assert m.fat_g == pytest.approx(44.4, abs=0.5)
    # Carbs = remainder ≈ 1600 - 102.4·4 - 44.4·9 = 1600 - 409.6 - 399.6 ≈ 790.8 kcal ≈ 197.7 g
    assert m.carbs_g == pytest.approx(197.7, abs=1)
    assert _sum_matches_kcal(m, 1600)


def test_protein_clamped_to_upper_amdr():
    """High goal-gpk × high body weight can exceed the 35% AMDR cap.

    After the upper-AMDR clamp (560 kcal = 140g at 1600 kcal target),
    the carbs-AMDR-floor backoff may reduce protein further to free
    kcal for carbs. We assert protein is ≤ 35% AMDR cap — the strict
    invariant — not equality, because the backoff is legal.
    """
    r = RationaleBuilder()
    # 120 kg × 1.6 g/kg = 192 g protein raw (768 kcal = 48% of 1600).
    m = compute_macros(
        kcal_target=1600,
        weight_kg=120,
        goals=GoalsInfo(goal_type="lose_weight"),
        dietary_needs=[],
        rationale=r,
    )
    protein_kcal = m.protein_g * KCAL_PER_G_PROTEIN
    # Never exceeds the AMDR upper (35% of kcal target).
    assert protein_kcal <= 0.35 * 1600 + 1
    # Never falls below the RDA floor (0.8 g/kg = 96 g = 384 kcal).
    assert protein_kcal >= 0.8 * 120 * KCAL_PER_G_PROTEIN - 1


def test_keto_raises_fat_fraction_but_clamped_by_backoff():
    r = RationaleBuilder()
    m = compute_macros(
        kcal_target=2000,
        weight_kg=70,
        goals=GoalsInfo(goal_type="maintain"),
        dietary_needs=["keto"],
        rationale=r,
    )
    # Keto pushes fat fraction to 0.65 of 2000 = 1300 kcal = 144.4 g fat.
    # Carbs must hit AMDR floor 45% = 900 kcal = 225 g. Protein at 1.2·70 = 84 g
    # = 336 kcal. Used kcal = 336 + 1300 = 1636. Carbs = 364 kcal = 91 g.
    # 91 g carbs < 900 kcal AMDR min → backoff reduces protein (floor 0.8 g/kg)
    # then fat to hit carb floor. Assert AMDR floor respected (within 1 kcal).
    carbs_kcal = m.carbs_g * KCAL_PER_G_CARBS
    assert carbs_kcal >= 0.45 * 2000 - 1


def test_maintain_goal_uses_1_2_gpk():
    r = RationaleBuilder()
    m = compute_macros(
        kcal_target=2200,
        weight_kg=70,
        goals=GoalsInfo(goal_type="maintain"),
        dietary_needs=[],
        rationale=r,
    )
    # 1.2 × 70 = 84 g (within AMDR at 2200).
    assert m.protein_g == pytest.approx(84, abs=0.5)


def test_macro_sum_always_equals_kcal_target():
    r = RationaleBuilder()
    m = compute_macros(
        kcal_target=2000,
        weight_kg=65,
        goals=GoalsInfo(goal_type="maintain"),
        dietary_needs=[],
        rationale=r,
    )
    total = (
        m.protein_g * KCAL_PER_G_PROTEIN + m.fat_g * KCAL_PER_G_FAT + m.carbs_g * KCAL_PER_G_CARBS
    )
    assert total == pytest.approx(2000, abs=2)


def test_rationale_records_three_macro_steps():
    r = RationaleBuilder()
    compute_macros(
        kcal_target=2000,
        weight_kg=70,
        goals=GoalsInfo(goal_type="maintain"),
        dietary_needs=[],
        rationale=r,
    )
    ids = [s.id for s in r.build(cohort="general_adult").steps]
    assert "protein_from_body_weight_then_amdr_clamp" in ids
    assert "fat_from_default_fraction" in ids
    assert "carbs_remainder_then_amdr_clamp" in ids
