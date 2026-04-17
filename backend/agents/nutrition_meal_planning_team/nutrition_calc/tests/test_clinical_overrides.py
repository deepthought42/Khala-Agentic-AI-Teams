"""SPEC-003 §6.1 / §6.2 — clinical overrides chain."""

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
from nutrition_meal_planning_team.nutrition_calc import compute_daily_targets


def _base_profile(clinical: ClinicalInfo) -> ClientProfile:
    return ClientProfile(
        client_id="c1",
        biometrics=BiometricInfo(
            sex=Sex.female,
            age_years=40,
            height_cm=168.0,
            weight_kg=70.0,
            activity_level=ActivityLevel.moderate,
        ),
        clinical=clinical,
    )


def test_hypertension_caps_sodium_at_1500():
    r = compute_daily_targets(_base_profile(ClinicalInfo(conditions=["hypertension"])))
    assert r.targets.sodium_mg == 1500.0
    assert "hypertension_sodium_cap" in r.rationale.applied_overrides


def test_ckd_3_caps_protein_at_0_8_gpk():
    clinical = ClinicalInfo(conditions=["ckd_stage_3"])
    r = compute_daily_targets(
        ClientProfile(
            client_id="c1",
            biometrics=BiometricInfo(
                sex=Sex.male,
                age_years=50,
                height_cm=180.0,
                weight_kg=80.0,
                activity_level=ActivityLevel.moderate,
            ),
            clinical=clinical,
            # Muscle goal normally pushes protein to 1.6 g/kg.
            goals=GoalsInfo(goal_type="muscle"),
        )
    )
    # Cap at 0.8 × 80 = 64 g.
    assert r.targets.protein_g == pytest.approx(64.0, abs=0.5)
    assert "ckd_protein_cap" in r.rationale.applied_overrides
    assert "ckd_phosphorus_caution" in r.rationale.applied_overrides


def test_t2d_adds_per_meal_carb_cap_metadata():
    r = compute_daily_targets(_base_profile(ClinicalInfo(conditions=["t2_diabetes"])))
    assert "per_meal_carb_cap_g" in r.metadata
    # Daily carbs / 3 rounded.
    expected = round(r.targets.carbs_g / 3.0)
    assert r.metadata["per_meal_carb_cap_g"] == expected
    assert "t2d_per_meal_carb_cap" in r.rationale.applied_overrides


def test_pregnancy_t2_adds_340_kcal():
    base = ClinicalInfo(reproductive_state=ReproductiveState.none)
    no_preg = compute_daily_targets(_base_profile(base))
    preg_t2 = compute_daily_targets(
        _base_profile(ClinicalInfo(reproductive_state=ReproductiveState.pregnant_t2))
    )
    # Pregnancy adds 340 kcal on top of maintenance; cohort is
    # pregnancy_lactation so no deficit is applied regardless.
    assert preg_t2.targets.calories_kcal == pytest.approx(
        no_preg.targets.calories_kcal + 340, abs=1
    )
    assert "reproductive_kcal_pregnant_t2" in preg_t2.rationale.applied_overrides


def test_lactation_adds_330_kcal():
    r = compute_daily_targets(
        _base_profile(ClinicalInfo(reproductive_state=ReproductiveState.lactating))
    )
    # TDEE for this profile:
    #   BMR = 10·70 + 6.25·168 − 5·40 − 161 = 700 + 1050 − 200 − 161 = 1389
    #   TDEE = 1389 × 1.55 = 2152.95
    #   Lactation adds 330 → ~2482.95
    assert r.targets.calories_kcal == pytest.approx(2152.95 + 330, abs=1)


def test_warfarin_tags_advisory_note():
    r = compute_daily_targets(_base_profile(ClinicalInfo(medications=["warfarin"])))
    assert "warfarin_vitamin_k" in r.metadata.get("advisory_notes", [])
    assert "warfarin_vitamin_k_advisory" in r.rationale.applied_overrides


def test_no_overrides_applied_for_bare_profile():
    r = compute_daily_targets(_base_profile(ClinicalInfo()))
    assert r.rationale.applied_overrides == ()


def test_hypertension_plus_ckd_both_apply():
    """Two compatible overrides run together."""
    r = compute_daily_targets(
        _base_profile(ClinicalInfo(conditions=["hypertension", "ckd_stage_3"]))
    )
    assert r.targets.sodium_mg == 1500.0
    # 0.8 × 70 = 56 g protein.
    assert r.targets.protein_g == pytest.approx(56.0, abs=0.5)
    applied = set(r.rationale.applied_overrides)
    assert {"hypertension_sodium_cap", "ckd_protein_cap"}.issubset(applied)
