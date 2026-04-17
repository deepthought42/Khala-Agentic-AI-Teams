"""SPEC-003 §6.3 — cohort router + failure-mode tests."""

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
    Cohort,
    InsufficientInputError,
    UnsupportedCohortError,
    compute_daily_targets,
)


def _full_biometrics(**overrides):
    base = dict(
        sex=Sex.female,
        age_years=30,
        height_cm=168.0,
        weight_kg=64.0,
        activity_level=ActivityLevel.moderate,
    )
    base.update(overrides)
    return BiometricInfo(**base)


def test_minor_routes_to_unsupported():
    p = ClientProfile(
        client_id="m1",
        biometrics=_full_biometrics(age_years=15),
    )
    with pytest.raises(UnsupportedCohortError) as exc_info:
        compute_daily_targets(p)
    assert exc_info.value.cohort == Cohort.MINOR
    assert exc_info.value.guidance_key == "minor"
    assert "pediatrician" in exc_info.value.clinician_note


def test_ckd_stage_4_routes_to_unsupported():
    p = ClientProfile(
        client_id="ck1",
        biometrics=_full_biometrics(),
        clinical=ClinicalInfo(conditions=["ckd_stage_4"]),
    )
    with pytest.raises(UnsupportedCohortError) as exc_info:
        compute_daily_targets(p)
    assert exc_info.value.cohort == Cohort.CLINICIAN_GUIDED
    assert exc_info.value.guidance_key == "ckd_stage_4"


def test_ckd_stage_5_routes_to_unsupported():
    p = ClientProfile(
        client_id="ck1",
        biometrics=_full_biometrics(),
        clinical=ClinicalInfo(conditions=["ckd_stage_5"]),
    )
    with pytest.raises(UnsupportedCohortError):
        compute_daily_targets(p)


def test_pregnancy_t2_routes_to_pregnancy_cohort():
    p = ClientProfile(
        client_id="pr1",
        biometrics=_full_biometrics(),
        clinical=ClinicalInfo(reproductive_state=ReproductiveState.pregnant_t2),
    )
    r = compute_daily_targets(p)
    assert r.cohort == Cohort.PREGNANCY_LACTATION


def test_lactation_routes_to_pregnancy_cohort():
    p = ClientProfile(
        client_id="la1",
        biometrics=_full_biometrics(),
        clinical=ClinicalInfo(reproductive_state=ReproductiveState.lactating),
    )
    r = compute_daily_targets(p)
    assert r.cohort == Cohort.PREGNANCY_LACTATION


def test_ed_flag_routes_to_ed_cohort():
    p = ClientProfile(
        client_id="ed1",
        biometrics=_full_biometrics(),
        clinical=ClinicalInfo(ed_history_flag=True),
        goals=GoalsInfo(goal_type="lose_weight", rate_kg_per_week=0.5),
    )
    r = compute_daily_targets(p)
    assert r.cohort == Cohort.ED_ADJACENT
    # ED cohort: no deficit applied even though goal asks for one.
    assert r.targets.calories_kcal == pytest.approx(r.intermediates["tdee_kcal"], abs=1)


def test_sex_unspecified_without_body_fat_routes_to_sex_avg_cohort():
    p = ClientProfile(
        client_id="sx1",
        biometrics=_full_biometrics(sex=Sex.unspecified),
    )
    r = compute_daily_targets(p)
    assert r.cohort == Cohort.GENERAL_ADULT_SEX_UNSPECIFIED


def test_sex_unspecified_with_body_fat_still_general_adult():
    """Katch-McArdle handles it; stays in general_adult cohort."""
    p = ClientProfile(
        client_id="sx2",
        biometrics=_full_biometrics(sex=Sex.unspecified, body_fat_pct=22.0),
    )
    r = compute_daily_targets(p)
    # Has body fat → not sex-avg branch → general_adult
    assert r.cohort == Cohort.GENERAL_ADULT


def test_missing_weight_raises_insufficient_input():
    p = ClientProfile(
        client_id="noweight",
        biometrics=_full_biometrics(weight_kg=None),
    )
    with pytest.raises(InsufficientInputError) as exc_info:
        compute_daily_targets(p)
    assert "weight_kg" in exc_info.value.fields


def test_missing_multiple_fields_reports_all():
    """Default-sex profile routes to GENERAL_ADULT_SEX_UNSPECIFIED,
    which does not require ``sex``; only age/height/weight are missing."""
    p = ClientProfile(
        client_id="none",
        biometrics=BiometricInfo(activity_level=ActivityLevel.moderate),
    )
    with pytest.raises(InsufficientInputError) as exc_info:
        compute_daily_targets(p)
    missing = set(exc_info.value.fields)
    assert missing == {"age_years", "height_cm", "weight_kg"}


def test_calculator_result_carries_version():
    p = ClientProfile(client_id="c1", biometrics=_full_biometrics())
    r = compute_daily_targets(p)
    from nutrition_meal_planning_team.nutrition_calc import CALCULATOR_VERSION

    assert r.calculator_version == CALCULATOR_VERSION
