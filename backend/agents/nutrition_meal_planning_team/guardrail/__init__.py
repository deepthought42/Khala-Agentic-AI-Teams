"""SPEC-007 guardrail pipeline — Phase 0 scaffolding.

W1 ships only the public surface area. ``check_recommendation`` is a
stub that raises ``NotImplementedError`` until W2 lands ``checker.py``.

Behaviour is gated by the ``NUTRITION_GUARDRAIL`` env var (off by
default), mirroring the SPEC-006 ``NUTRITION_RESTRICTION_RESOLVER``
pattern.
"""

from __future__ import annotations

import os

from .errors import GuardrailError, GuardrailNotImplementedError
from .version import GUARDRAIL_VERSION
from .violations import GuardrailResult, Severity, Violation, ViolationReason

_FLAG = "NUTRITION_GUARDRAIL"


def is_guardrail_enabled() -> bool:
    """Read at every call site so env can flip without restart."""
    return os.environ.get(_FLAG, "0") == "1"


def check_recommendation(profile, rec):
    """SPEC-007 entrypoint. Stub until W2 implements ``checker.py``."""
    raise GuardrailNotImplementedError("check_recommendation is implemented in SPEC-007 W2")


__all__ = [
    "GUARDRAIL_VERSION",
    "GuardrailError",
    "GuardrailResult",
    "Severity",
    "Violation",
    "ViolationReason",
    "check_recommendation",
    "is_guardrail_enabled",
]
