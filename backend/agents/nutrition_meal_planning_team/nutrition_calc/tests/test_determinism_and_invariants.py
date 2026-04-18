"""SPEC-003 §6.4 — property + determinism tests.

These are NOT randomized hypothesis tests (hypothesis isn't a hard
repo dep); they're hand-rolled invariant checks over a handful of
parametric fixtures, which is sufficient for v1 guarantees.
"""

from __future__ import annotations

import pytest

from nutrition_meal_planning_team.models import (
    ActivityLevel,
    BiometricInfo,
    ClientProfile,
    GoalsInfo,
    Sex,
)
from nutrition_meal_planning_team.nutrition_calc import compute_daily_targets
from nutrition_meal_planning_team.nutrition_calc.macros import (
    KCAL_PER_G_CARBS,
    KCAL_PER_G_FAT,
    KCAL_PER_G_PROTEIN,
)


def _profile(**bio_overrides):
    base = dict(
        sex=Sex.female,
        age_years=30,
        height_cm=168.0,
        weight_kg=64.0,
        activity_level=ActivityLevel.moderate,
    )
    base.update(bio_overrides)
    return ClientProfile(client_id="c1", biometrics=BiometricInfo(**base))


# --- Determinism ---------------------------------------------------------


def test_same_inputs_same_outputs_byte_for_byte():
    """Running the calculator twice with identical inputs returns byte-
    equal DailyTargets and the same rationale step sequence."""
    p = _profile()
    r1 = compute_daily_targets(p)
    r2 = compute_daily_targets(p)
    assert r1.targets.model_dump() == r2.targets.model_dump()
    assert [s.id for s in r1.rationale.steps] == [s.id for s in r2.rationale.steps]


# --- Invariants ----------------------------------------------------------


def test_macro_kcal_sum_within_2_of_target():
    """Sum of macro kcal contributions matches target within rounding."""
    r = compute_daily_targets(_profile())
    total_kcal = (
        r.targets.protein_g * KCAL_PER_G_PROTEIN
        + r.targets.carbs_g * KCAL_PER_G_CARBS
        + r.targets.fat_g * KCAL_PER_G_FAT
    )
    assert total_kcal == pytest.approx(r.targets.calories_kcal, abs=2)


@pytest.mark.parametrize("goal_type", ["maintain", "lose_weight", "gain_weight", "muscle"])
def test_protein_within_rda_to_practical_ceiling(goal_type):
    """Protein lands between 0.8 and 2.2 g/kg for any well-formed goal."""
    p = _profile()
    p.goals = GoalsInfo(goal_type=goal_type, rate_kg_per_week=0.3)
    r = compute_daily_targets(p)
    protein_gpk = r.targets.protein_g / p.biometrics.weight_kg
    assert 0.8 <= protein_gpk <= 2.2, f"{goal_type}: {protein_gpk} g/kg"


def test_kcal_target_never_below_safety_floor():
    """Even aggressive loss on a small frame stays ≥ safety floor."""
    p = _profile(weight_kg=45.0)
    p.goals = GoalsInfo(goal_type="lose_weight", rate_kg_per_week=1.0)
    r = compute_daily_targets(p)
    # Floor is max(1200, 0.8·BMR). BMR for 45kg female = 10·45+6.25·168−5·30−161
    # = 450+1050−150−161 = 1189; 0.8·BMR ≈ 951 → floor = 1200.
    assert r.targets.calories_kcal >= 1200.0


def test_monotonic_kcal_over_weight_general_adult():
    """Holding everything else equal, more body weight → more kcal."""
    low = compute_daily_targets(_profile(weight_kg=55.0))
    high = compute_daily_targets(_profile(weight_kg=85.0))
    assert high.targets.calories_kcal > low.targets.calories_kcal
    # Protein is gram-per-kg so it also rises monotonically.
    assert high.targets.protein_g > low.targets.protein_g
