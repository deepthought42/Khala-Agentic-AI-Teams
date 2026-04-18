"""SPEC-003 §6.1 — Mifflin-St Jeor + Katch-McArdle reference values."""

from __future__ import annotations

import pytest

from nutrition_meal_planning_team.models import Sex
from nutrition_meal_planning_team.nutrition_calc.bmr import compute_bmr
from nutrition_meal_planning_team.nutrition_calc.rationale import RationaleBuilder


@pytest.mark.parametrize(
    "sex,kg,cm,age,expected",
    [
        # Mifflin-St Jeor worked examples. Expected = 10·kg + 6.25·cm − 5·age + (+5|−161|−78)
        # Verified against hand calculation:
        # female 64.5/168/32: 10·64.5 + 6.25·168 − 5·32 − 161 = 645 + 1050 − 160 − 161 = 1374
        # female 55/160/45:  10·55  + 6.25·160 − 5·45 − 161 = 550 + 1000 − 225 − 161 = 1164
        # female 72/175/28:  10·72  + 6.25·175 − 5·28 − 161 = 720 + 1093.75 − 140 − 161 = 1512.75
        # male   80/180/30:  10·80  + 6.25·180 − 5·30 + 5   = 800 + 1125 − 150 + 5 = 1780
        # male   90/185/45:  10·90  + 6.25·185 − 5·45 + 5   = 900 + 1156.25 − 225 + 5 = 1836.25
        # male   70/175/60:  10·70  + 6.25·175 − 5·60 + 5   = 700 + 1093.75 − 300 + 5 = 1498.75
        (Sex.female, 64.5, 168.0, 32, 1374.0),
        (Sex.female, 55.0, 160.0, 45, 1164.0),
        (Sex.female, 72.0, 175.0, 28, 1512.75),
        (Sex.male, 80.0, 180.0, 30, 1780.0),
        (Sex.male, 90.0, 185.0, 45, 1836.25),
        (Sex.male, 70.0, 175.0, 60, 1498.75),
    ],
)
def test_mifflin_reference(sex, kg, cm, age, expected):
    r = RationaleBuilder()
    result = compute_bmr(sex=sex, kg=kg, cm=cm, age=age, body_fat_pct=None, rationale=r)
    assert result.equation == f"mifflin_{sex.value}"
    assert result.kcal == pytest.approx(expected, abs=0.5)


@pytest.mark.parametrize(
    "sex",
    [Sex.other, Sex.unspecified],
)
def test_mifflin_sex_averaged_midpoint(sex):
    """Midpoint of the two Mifflin variants is ``base − 78``."""
    r = RationaleBuilder()
    result = compute_bmr(sex=sex, kg=70.0, cm=175.0, age=40, body_fat_pct=None, rationale=r)
    # 10·70 + 6.25·175 − 5·40 − 78 = 700 + 1093.75 − 200 − 78 = 1515.75
    assert result.kcal == pytest.approx(1515.75, abs=0.1)
    assert result.equation == f"mifflin_{sex.value}"


@pytest.mark.parametrize(
    "kg,bf_pct,expected",
    [
        # Katch-McArdle: BMR = 370 + 21.6 · (kg · (1 − bf/100))
        (70.0, 20.0, 370 + 21.6 * 70.0 * 0.8),  # 1579.6
        (80.0, 25.0, 370 + 21.6 * 80.0 * 0.75),  # 1666.0
        (55.0, 18.0, 370 + 21.6 * 55.0 * 0.82),  # 1344.16
    ],
)
def test_katch_mcardle_reference(kg, bf_pct, expected):
    r = RationaleBuilder()
    result = compute_bmr(sex=Sex.female, kg=kg, cm=170.0, age=30, body_fat_pct=bf_pct, rationale=r)
    assert result.equation == "katch_mcardle"
    assert result.kcal == pytest.approx(expected, abs=0.2)


def test_katch_used_when_body_fat_present_regardless_of_sex():
    """Same BMR for female / male / other when body fat is given."""
    r1 = RationaleBuilder()
    r2 = RationaleBuilder()
    r3 = RationaleBuilder()
    a = compute_bmr(sex=Sex.female, kg=70, cm=170, age=30, body_fat_pct=20, rationale=r1)
    b = compute_bmr(sex=Sex.male, kg=70, cm=170, age=30, body_fat_pct=20, rationale=r2)
    c = compute_bmr(sex=Sex.unspecified, kg=70, cm=170, age=30, body_fat_pct=20, rationale=r3)
    assert a.kcal == b.kcal == c.kcal


def test_rationale_step_recorded():
    r = RationaleBuilder()
    compute_bmr(sex=Sex.female, kg=64.5, cm=168, age=32, body_fat_pct=None, rationale=r)
    built = r.build(cohort="general_adult")
    assert len(built.steps) == 1
    step = built.steps[0]
    assert step.id == "bmr_mifflin_female"
    assert "bmr_kcal" in step.outputs


def test_rationale_sex_unspecified_has_note():
    r = RationaleBuilder()
    compute_bmr(sex=Sex.unspecified, kg=70, cm=175, age=40, body_fat_pct=None, rationale=r)
    built = r.build(cohort="general_adult_sex_unspecified")
    assert built.steps[0].note == "sex-averaged midpoint used (sex unspecified)"
