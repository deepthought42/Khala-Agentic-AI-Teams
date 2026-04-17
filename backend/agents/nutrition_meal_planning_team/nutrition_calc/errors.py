"""Error types raised by the deterministic calculator.

All three failure modes are represented with structured payloads so
the agent narrator (SPEC-004) can branch on cohort / missing-field
information without string-parsing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class CalculatorError(Exception):
    """Base for nutrition_calc failures."""


@dataclass
class InsufficientInputError(CalculatorError):
    """A required field is missing for the routed cohort.

    ``fields`` names the missing profile fields. The agent narrator
    uses this list to render a "we need your height/weight/..." note
    rather than guessing.
    """

    fields: tuple[str, ...] = field(default_factory=tuple)
    cohort: str = "general_adult"
    message: str = ""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message or f"insufficient inputs: {list(self.fields)}"


@dataclass
class ImplausibleInputError(CalculatorError):
    """An input bypassed the profile's own validators and is
    biologically implausible.

    This should never reach the calculator in practice — SPEC-002's
    Pydantic validators catch implausibility at the API boundary.
    Treat as a bug if it fires; log and surface as an internal error.
    """

    field: str = ""
    value: Optional[float] = None
    reason: str = ""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return (
            f"implausible {self.field}={self.value}: {self.reason}"
            if self.field
            else self.reason or "implausible input"
        )


@dataclass
class UnsupportedCohortError(CalculatorError):
    """The profile routes to a cohort the calculator deliberately does
    not emit numeric targets for.

    Minors and CKD stage 4-5 fall here. The agent narrator branches to
    a guidance-only response using ``guidance_key`` as the prompt
    switch. This is not an error the user sees as a failure — it is
    a successful "work with your clinician" response path.
    """

    cohort: str = ""
    guidance_key: str = ""
    clinician_note: str = ""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"unsupported cohort: {self.cohort}"
