"""SPEC-007 §4.3 public types — violation reasons, severity, and result.

Pure data. No I/O, no LLM. Frozen dataclasses so a ``GuardrailResult``
is safe to hash, log, and replay deterministically.

The spec calls ``ViolationReason`` a ``StrEnum``; on Python 3.10 we use
the team's ``(str, Enum)`` idiom (see ``ingredient_kb.taxonomy``), which
is ``isinstance`` of ``str`` and behaves identically for our needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..ingredient_kb.types import ParsedIngredient


class Severity(str, Enum):
    """Whether a violation blocks the recommendation or just decorates it."""

    hard_reject = "hard_reject"
    flag = "flag"


class ViolationReason(str, Enum):
    """Why the guardrail rejected or flagged a recommendation."""

    allergen = "allergen"
    dietary_forbid = "dietary_forbid"
    unresolved_ingredient = "unresolved_ingredient"
    interaction_hard = "interaction_hard"
    interaction_flag = "interaction_flag"


@dataclass(frozen=True)
class Violation:
    """One reason a recommendation failed (or was flagged by) the guardrail."""

    reason: ViolationReason
    ingredient_raw: str
    canonical_id: Optional[str]
    tag: Optional[str]
    detail: str
    severity: Severity


@dataclass(frozen=True)
class GuardrailResult:
    """Outcome of ``check_recommendation``.

    ``violations`` are ``hard_reject`` entries that block the rec;
    ``flags`` are non-blocking ``flag`` entries surfaced in the UI.
    ``parsed_ingredients`` is reused by ADR-003 callers.
    """

    passed: bool
    violations: tuple[Violation, ...]
    flags: tuple[Violation, ...]
    parsed_ingredients: tuple[ParsedIngredient, ...]
