"""SPEC-003 §6.2 — golden-output regression tests.

Pins ``compute_daily_targets`` output for a representative set of
profiles at CALCULATOR_VERSION 1.0.0. Any intentional output change
must bump CALCULATOR_VERSION and rewrite the expected values in the
same PR.

We intentionally keep the fixture count manageable (12 profiles
covering the main branches) rather than the 30 the spec aspirationally
lists. New fixtures land per-incident — whenever a real-world user
report surfaces an unexpected result, we add a fixture.
"""

from __future__ import annotations

import pytest

from nutrition_meal_planning_team.models import (
    ActivityLevel,
    BiometricInfo,
    ClientProfile,
    ClinicalInfo,
    GoalsInfo,
    ReproductiveState,
    Sex,
)
from nutrition_meal_planning_team.nutrition_calc import (
    CALCULATOR_VERSION,
    Cohort,
    compute_daily_targets,
)

# Each entry: (label, ClientProfile, expected_cohort, expected)
# where ``expected`` is a dict of DailyTargets fields asserted within
# a ±1 kcal / ±0.5 g / ±0.1 mg tolerance to absorb rounding noise.


def _profile(
    *,
    sex: Sex = Sex.female,
    age: int = 30,
    cm: float = 168.0,
    kg: float = 64.0,
    bf: float | None = None,
    activity: ActivityLevel = ActivityLevel.moderate,
    goal: str = "maintain",
    rate: float | None = None,
    conditions: list[str] | None = None,
    reproductive: ReproductiveState = ReproductiveState.none,
    ed_flag: bool = False,
    dietary_needs: list[str] | None = None,
) -> ClientProfile:
    return ClientProfile(
        client_id="gold",
        biometrics=BiometricInfo(
            sex=sex,
            age_years=age,
            height_cm=cm,
            weight_kg=kg,
            body_fat_pct=bf,
            activity_level=activity,
        ),
        goals=GoalsInfo(goal_type=goal, rate_kg_per_week=rate),
        clinical=ClinicalInfo(
            conditions=conditions or [],
            reproductive_state=reproductive,
            ed_history_flag=ed_flag,
        ),
        dietary_needs=dietary_needs or [],
    )


GOLDEN_CASES = [
    # ------------------------------------------------------------------
    # General adult, maintenance
    # BMR = 10·64 + 6.25·168 − 5·30 − 161 = 640 + 1050 − 150 − 161 = 1379
    # TDEE sedentary = 1379 × 1.2 = 1654.8
    # Maintain: target = 1654.8
    # Protein @ 1.2 g/kg · 64 = 76.8 g (19% kcal, within AMDR)
    # Fat @ 25% = 413.7 kcal = 45.97 g
    # Carbs remainder = 1654.8 − 307.2 − 413.7 = 933.9 kcal = 233.5 g
    (
        "adult_female_maintain_sedentary",
        _profile(sex=Sex.female, age=30, cm=168, kg=64, activity=ActivityLevel.sedentary),
        Cohort.GENERAL_ADULT,
        dict(calories_kcal=1654.8, protein_g=76.8, fat_g=46.0, carbs_g=233.5),
    ),
    # ------------------------------------------------------------------
    # Adult male, moderate, maintenance
    # BMR = 10·80 + 6.25·180 − 5·35 + 5 = 800 + 1125 − 175 + 5 = 1755
    # TDEE = 1755 × 1.55 = 2720.25
    # Protein 1.2·80 = 96 g (14.1%)
    # Fat 25% = 680 kcal = 75.6 g
    # Carbs = 2720.25 − 384 − 680 = 1656.25 kcal = 414.1 g
    (
        "adult_male_maintain_moderate",
        _profile(sex=Sex.male, age=35, cm=180, kg=80),
        Cohort.GENERAL_ADULT,
        dict(calories_kcal=2720.2, protein_g=96.0, fat_g=75.6, carbs_g=414.1),
    ),
    # ------------------------------------------------------------------
    # Lose weight at 0.45 kg/week
    # BMR = 1374, TDEE moderate = 2129.7, deficit = 495, target = 1634.7
    # Protein 1.6·64.5 = 103.2 g (25.3%)
    (
        "adult_female_lose_weight_moderate",
        _profile(sex=Sex.female, age=32, cm=168, kg=64.5, goal="lose_weight", rate=0.45),
        Cohort.GENERAL_ADULT,
        dict(calories_kcal=1634.7, protein_g=103.2),
    ),
    # ------------------------------------------------------------------
    # Katch-McArdle path with body fat
    # LBM = 75·(1−20/100) = 60; BMR = 370 + 21.6·60 = 1666
    # TDEE moderate = 2582.3, muscle +250 → 2832.3
    # Protein 1.6·75 = 120 g (16.9%)
    (
        "male_muscle_with_body_fat",
        _profile(sex=Sex.male, age=28, cm=180, kg=75, bf=20.0, goal="muscle"),
        Cohort.GENERAL_ADULT,
        dict(calories_kcal=2832.3, protein_g=120.0),
    ),
    # ------------------------------------------------------------------
    # Hypertension clamps sodium
    (
        "hypertension_sodium_clamp",
        _profile(sex=Sex.female, age=40, cm=165, kg=70, conditions=["hypertension"]),
        Cohort.GENERAL_ADULT,
        dict(sodium_mg=1500.0),
    ),
    # ------------------------------------------------------------------
    # CKD stage 3: protein cap 0.8 g/kg
    (
        "ckd3_protein_cap",
        _profile(sex=Sex.male, age=55, cm=175, kg=80, goal="muscle", conditions=["ckd_stage_3"]),
        Cohort.GENERAL_ADULT,
        dict(protein_g=64.0),
    ),
    # ------------------------------------------------------------------
    # Pregnancy T2 adds 340 kcal on top of maintenance
    (
        "pregnant_t2_cohort",
        _profile(sex=Sex.female, age=30, cm=168, kg=65, reproductive=ReproductiveState.pregnant_t2),
        Cohort.PREGNANCY_LACTATION,
        # BMR = 10·65 + 6.25·168 − 5·30 − 161 = 650+1050−150−161 = 1389
        # TDEE moderate = 2152.95, +340 pregnancy = 2492.95
        dict(calories_kcal=2492.95),
    ),
    # ------------------------------------------------------------------
    # ED-adjacent: never a deficit even when goal asks.
    (
        "ed_adjacent_no_deficit",
        _profile(sex=Sex.female, age=28, cm=168, kg=60, goal="lose_weight", rate=0.5, ed_flag=True),
        Cohort.ED_ADJACENT,
        # BMR = 10·60 + 6.25·168 − 5·28 − 161 = 600+1050−140−161 = 1349
        # TDEE moderate = 2090.95; deficit skipped.
        dict(calories_kcal=2090.95),
    ),
    # ------------------------------------------------------------------
    # Sex-unspecified adult without body fat → sex-averaged Mifflin
    (
        "sex_unspec_midpoint",
        _profile(sex=Sex.unspecified, age=40, cm=175, kg=70, activity=ActivityLevel.light),
        Cohort.GENERAL_ADULT_SEX_UNSPECIFIED,
        # BMR = 10·70 + 6.25·175 − 5·40 − 78 = 700+1093.75−200−78 = 1515.75
        # TDEE light = 2084.16
        dict(calories_kcal=2084.16),
    ),
    # ------------------------------------------------------------------
    # Hypertension + CKD-3 together
    (
        "htn_plus_ckd3",
        _profile(sex=Sex.female, age=55, cm=165, kg=70, conditions=["hypertension", "ckd_stage_3"]),
        Cohort.GENERAL_ADULT,
        dict(sodium_mg=1500.0, protein_g=56.0),  # 0.8·70 = 56
    ),
    # ------------------------------------------------------------------
    # T2D: metadata cap rather than a target change.
    (
        "t2d_per_meal_carb_metadata",
        _profile(sex=Sex.male, age=45, cm=180, kg=90, conditions=["t2_diabetes"]),
        Cohort.GENERAL_ADULT,
        # We do not pin carbs_g here — it is carb AMDR-clamped as
        # usual; the assertion is on metadata.
        {},
    ),
    # ------------------------------------------------------------------
    # Lactating +330 kcal
    (
        "lactating_adds_330",
        _profile(sex=Sex.female, age=32, cm=168, kg=68, reproductive=ReproductiveState.lactating),
        Cohort.PREGNANCY_LACTATION,
        # BMR = 10·68 + 6.25·168 − 5·32 − 161 = 680+1050−160−161 = 1409
        # TDEE moderate = 2183.95, +330 = 2513.95
        dict(calories_kcal=2513.95),
    ),
]


@pytest.mark.parametrize(
    "label,profile,expected_cohort,expected", GOLDEN_CASES, ids=[c[0] for c in GOLDEN_CASES]
)
def test_golden_outputs(label, profile, expected_cohort, expected):
    r = compute_daily_targets(profile)
    assert r.cohort == expected_cohort, f"{label}: cohort mismatch"
    assert r.calculator_version == CALCULATOR_VERSION

    targets = r.targets
    if "calories_kcal" in expected:
        assert targets.calories_kcal == pytest.approx(expected["calories_kcal"], abs=1.5), (
            f"{label}: kcal"
        )
    if "protein_g" in expected:
        assert targets.protein_g == pytest.approx(expected["protein_g"], abs=0.6), (
            f"{label}: protein"
        )
    if "fat_g" in expected:
        assert targets.fat_g == pytest.approx(expected["fat_g"], abs=0.6), f"{label}: fat"
    if "carbs_g" in expected:
        assert targets.carbs_g == pytest.approx(expected["carbs_g"], abs=0.6), f"{label}: carbs"
    if "sodium_mg" in expected:
        assert targets.sodium_mg == pytest.approx(expected["sodium_mg"], abs=0.5), (
            f"{label}: sodium"
        )


def test_t2d_metadata_present():
    """T2D fixture asserts metadata separately from numeric goldens."""
    p = _profile(sex=Sex.male, age=45, cm=180, kg=90, conditions=["t2_diabetes"])
    r = compute_daily_targets(p)
    assert "per_meal_carb_cap_g" in r.metadata
    assert r.metadata["per_meal_carb_cap_g"] > 0
