"""Deterministic nutrition calculator (SPEC-003).

Pure-Python module with no LLM, Postgres, or agent dependencies.
Public entry points:

    from nutrition_meal_planning_team.nutrition_calc import (
        compute_daily_targets, CALCULATOR_VERSION,
        CalculatorError, InsufficientInputError,
        ImplausibleInputError, UnsupportedCohortError,
        Rationale, RationaleStep, Cohort,
    )

``compute_daily_targets(profile) -> CalculatorResult`` is the only
entry point downstream consumers should rely on. Everything else is
an implementation detail of the computation pipeline.
"""

from __future__ import annotations

from .errors import (
    CalculatorError,
    ImplausibleInputError,
    InsufficientInputError,
    UnsupportedCohortError,
)
from .rationale import Rationale, RationaleStep
from .targets import CalculatorResult, Cohort, compute_daily_targets
from .version import CALCULATOR_VERSION

__all__ = [
    "CALCULATOR_VERSION",
    "CalculatorError",
    "CalculatorResult",
    "Cohort",
    "ImplausibleInputError",
    "InsufficientInputError",
    "Rationale",
    "RationaleStep",
    "UnsupportedCohortError",
    "compute_daily_targets",
]
