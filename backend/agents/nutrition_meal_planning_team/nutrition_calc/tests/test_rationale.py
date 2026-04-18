"""SPEC-003 §6.1 — Rationale / RationaleStep / RationaleBuilder."""

from __future__ import annotations

import pytest

from nutrition_meal_planning_team.nutrition_calc.rationale import (
    Rationale,
    RationaleBuilder,
    RationaleStep,
)


def test_step_is_frozen():
    """RationaleStep is immutable (dataclass frozen=True)."""
    step = RationaleStep(id="t", label="l", inputs={"a": 1}, outputs={"b": 2}, source="src")
    with pytest.raises(Exception):
        step.id = "other"  # type: ignore[misc]


def test_builder_appends_in_order():
    b = RationaleBuilder()
    b.add(step_id="first", label="first", inputs={}, outputs={}, source="src")
    b.add(step_id="second", label="second", inputs={}, outputs={}, source="src")
    built = b.build(cohort="general_adult")
    assert [s.id for s in built.steps] == ["first", "second"]
    assert built.cohort == "general_adult"


def test_builder_marks_unique_overrides():
    b = RationaleBuilder()
    b.mark_override("a")
    b.mark_override("b")
    b.mark_override("a")  # dup
    built = b.build(cohort="general_adult")
    assert built.applied_overrides == ("a", "b")


def test_built_rationale_is_frozen_immutable():
    built = RationaleBuilder().build(cohort="general_adult")
    assert isinstance(built, Rationale)
    with pytest.raises(Exception):
        built.cohort = "other"  # type: ignore[misc]


def test_step_inputs_are_copied_not_aliased():
    """Mutating the input dict after add() does not corrupt the step."""
    b = RationaleBuilder()
    inputs = {"x": 1}
    b.add(step_id="s", label="s", inputs=inputs, outputs={}, source="src")
    inputs["x"] = 99
    step = b.build(cohort="general_adult").steps[0]
    assert step.inputs == {"x": 1}
