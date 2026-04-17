"""Structured audit trail of calculator decisions.

Every function in bmr/tdee/energy_goal/macros/micros/clinical_overrides
appends exactly one ``RationaleStep`` as it runs. The resulting
``Rationale`` is returned on ``CalculatorResult`` and rendered by
SPEC-022's "why these numbers?" UI panel.

Rationale is what makes the output reviewable. It is also what lets
us tell a user *why* their target moved when the calculator version
bumps — we show them the diff between the two rationales.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class RationaleStep:
    """One computation step.

    The tuple ``(id, inputs, outputs)`` is the audit-level record.
    ``label`` and ``source`` drive UI display. ``note`` is reserved
    for non-obvious caveats (e.g. "applied sex-averaged BMR because
    sex=unspecified").
    """

    id: str
    label: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    source: str
    note: Optional[str] = None


@dataclass(frozen=True)
class Rationale:
    """Complete ordered audit of a single calculation.

    ``applied_overrides`` lists the IDs of clinical overrides that
    fired (e.g. ``("hypertension_sodium_cap",)``). Empty tuple when
    no overrides matched the profile.
    """

    steps: tuple[RationaleStep, ...] = field(default_factory=tuple)
    applied_overrides: tuple[str, ...] = field(default_factory=tuple)
    cohort: str = "general_adult"


class RationaleBuilder:
    """Mutable builder used during compute_daily_targets.

    The calculator's public API returns an immutable ``Rationale``.
    During the compute pass we need append semantics, so the builder
    collects steps and is frozen at the end via ``build(cohort)``.
    """

    def __init__(self) -> None:
        self._steps: list[RationaleStep] = []
        self._applied_overrides: list[str] = []

    def add(
        self,
        *,
        step_id: str,
        label: str,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        source: str,
        note: Optional[str] = None,
    ) -> None:
        self._steps.append(
            RationaleStep(
                id=step_id,
                label=label,
                inputs=dict(inputs),
                outputs=dict(outputs),
                source=source,
                note=note,
            )
        )

    def mark_override(self, override_id: str) -> None:
        if override_id not in self._applied_overrides:
            self._applied_overrides.append(override_id)

    def build(self, cohort: str) -> Rationale:
        return Rationale(
            steps=tuple(self._steps),
            applied_overrides=tuple(self._applied_overrides),
            cohort=cohort,
        )
