"""SPEC-002 W4 support: unit conversion tests."""

from __future__ import annotations

import pytest

from nutrition_meal_planning_team.units import (
    CM_PER_INCH,
    KG_PER_LB,
    cm_to_ft_in,
    coerce_height_cm,
    coerce_weight_kg,
    ft_in_to_cm,
    inches_to_cm,
    kg_to_lb,
    lb_to_kg,
)

# --- Direct conversions --------------------------------------------------


def test_inches_to_cm_exact():
    assert inches_to_cm(1) == CM_PER_INCH
    assert inches_to_cm(10) == pytest.approx(25.4, abs=1e-9)


def test_ft_in_to_cm_matches_inches():
    assert ft_in_to_cm(5, 10) == pytest.approx(177.8, abs=1e-9)
    assert ft_in_to_cm(6, 0) == pytest.approx(182.88, abs=1e-9)


def test_cm_to_ft_in_roundtrip():
    ft, inches = cm_to_ft_in(177.8)
    assert ft == 5
    assert inches == pytest.approx(10, abs=1e-6)


def test_lb_to_kg_exact():
    assert lb_to_kg(1) == KG_PER_LB
    assert lb_to_kg(150) == pytest.approx(68.038855, abs=1e-4)


def test_kg_to_lb_roundtrip():
    for kg in (50.0, 65.5, 100.0):
        assert kg_to_lb(lb_to_kg(kg / KG_PER_LB)) == pytest.approx(kg / KG_PER_LB)


# --- coerce_height_cm ----------------------------------------------------


def test_coerce_height_cm_prefers_canonical():
    assert coerce_height_cm(height_cm=170.0) == 170.0


def test_coerce_height_cm_uses_canonical_over_imperial():
    # When both provided, cm wins (user explicit on canonical).
    assert coerce_height_cm(height_cm=170.0, height_ft=5, height_in=0) == 170.0


def test_coerce_height_cm_from_ft_in():
    result = coerce_height_cm(height_ft=5, height_in=10)
    assert result == pytest.approx(177.8, abs=1e-6)


def test_coerce_height_cm_ft_only():
    assert coerce_height_cm(height_ft=6) == pytest.approx(182.88, abs=1e-6)


def test_coerce_height_cm_in_only():
    assert coerce_height_cm(height_in=70) == pytest.approx(177.8, abs=1e-6)


def test_coerce_height_cm_all_none_returns_none():
    assert coerce_height_cm() is None
    assert coerce_height_cm(height_cm=None, height_ft=None, height_in=None) is None


def test_coerce_height_cm_zero_inputs_return_none():
    # 0 ft 0 in is explicitly "empty" — not a silent 0 cm fallback.
    assert coerce_height_cm(height_ft=0, height_in=0) is None


def test_coerce_height_cm_treats_zero_cm_as_missing():
    # A 0 cm input is sentinel for "not given"; we fall through to imperial.
    assert coerce_height_cm(height_cm=0, height_ft=5, height_in=10) == pytest.approx(
        177.8, abs=1e-6
    )


# --- coerce_weight_kg ----------------------------------------------------


def test_coerce_weight_kg_prefers_kg():
    assert coerce_weight_kg(weight_kg=75.0) == 75.0


def test_coerce_weight_kg_from_lb():
    assert coerce_weight_kg(weight_lb=150) == pytest.approx(68.038855, abs=1e-4)


def test_coerce_weight_kg_none_returns_none():
    assert coerce_weight_kg() is None
    assert coerce_weight_kg(weight_kg=None, weight_lb=None) is None


def test_coerce_weight_kg_zero_kg_falls_through_to_lb():
    assert coerce_weight_kg(weight_kg=0, weight_lb=150) == pytest.approx(68.038855, abs=1e-4)


def test_coerce_weight_kg_zero_lb_returns_none():
    assert coerce_weight_kg(weight_lb=0) is None
