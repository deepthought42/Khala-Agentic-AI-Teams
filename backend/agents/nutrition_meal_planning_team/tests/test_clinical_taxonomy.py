"""SPEC-002 W2: clinical taxonomy tests."""

from __future__ import annotations

from nutrition_meal_planning_team.clinical_taxonomy import (
    CKD_STAGES,
    CLINICAL_TAXONOMY_VERSION,
    CLINICIAN_GUIDED_ONLY,
    DIABETES,
    Condition,
    Medication,
    is_known_condition,
    is_known_medication,
    parse_conditions,
    parse_medications,
)


def test_version_exported():
    assert isinstance(CLINICAL_TAXONOMY_VERSION, str)
    assert CLINICAL_TAXONOMY_VERSION.count(".") == 2


def test_known_conditions_round_trip():
    for c in Condition:
        assert is_known_condition(c.value)


def test_known_medications_round_trip():
    for m in Medication:
        assert is_known_medication(m.value)


def test_unknown_condition_rejected():
    assert not is_known_condition("grandma's special condition")
    assert not is_known_condition("")


def test_unknown_medication_rejected():
    assert not is_known_medication("some random herb")


def test_parse_conditions_splits_known_and_unknown():
    known, unknown = parse_conditions(
        ["hypertension", "dyslipidemia", "random-thing", "hypertension"]
    )
    # Dedup and split; order preserved.
    assert known == [Condition.hypertension, Condition.dyslipidemia]
    assert unknown == ["random-thing"]


def test_parse_conditions_empty_input():
    known, unknown = parse_conditions([])
    assert known == []
    assert unknown == []


def test_parse_conditions_ignores_empty_strings():
    known, unknown = parse_conditions(["", "  ", "hypertension"])
    assert known == [Condition.hypertension]
    assert unknown == []


def test_parse_medications_splits_known_and_unknown():
    known, unknown = parse_medications(["warfarin", "some-supplement"])
    assert known == [Medication.warfarin]
    assert unknown == ["some-supplement"]


def test_ckd_stages_convenience_set():
    assert Condition.ckd_stage_3 in CKD_STAGES
    assert Condition.hypertension not in CKD_STAGES


def test_clinician_guided_only_includes_ckd_45():
    assert Condition.ckd_stage_4 in CLINICIAN_GUIDED_ONLY
    assert Condition.ckd_stage_5 in CLINICIAN_GUIDED_ONLY
    assert Condition.ckd_stage_3 not in CLINICIAN_GUIDED_ONLY


def test_diabetes_convenience_set():
    assert Condition.t1_diabetes in DIABETES
    assert Condition.t2_diabetes in DIABETES
    assert Condition.prediabetes in DIABETES
    assert Condition.ckd_stage_1 not in DIABETES
