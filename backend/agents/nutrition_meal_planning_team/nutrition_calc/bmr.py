"""Basal Metabolic Rate (BMR) equations.

SPEC-003 §4.3. Two equations:

- **Mifflin–St Jeor** (default). ISSN 2017 position paper prefers it
  over Harris–Benedict for modern adults.

  female: 10·kg + 6.25·cm − 5·age − 161
  male:   10·kg + 6.25·cm − 5·age + 5

- **Katch–McArdle** (preferred when ``body_fat_pct`` is available):

  BMR = 370 + 21.6 · LBM_kg
  LBM_kg = kg · (1 − body_fat_pct / 100)

  Sex-independent; we use it regardless of ``Sex`` when body fat is
  present.

For ``Sex.other`` / ``Sex.unspecified`` without body fat, we fall
back to the sex-averaged Mifflin variant (midpoint of ``−161`` and
``+5``):

  10·kg + 6.25·cm − 5·age − 78

and the rationale records the approximation.
"""

from __future__ import annotations

from typing import Optional

from ..models import Sex
from .rationale import RationaleBuilder

__all__ = ["compute_bmr", "BMRResult"]


class BMRResult:
    """Lightweight result holder — plain class, not a dataclass, so
    it can carry the chosen equation tag without leaking into Rationale.
    """

    __slots__ = ("kcal", "equation")

    def __init__(self, kcal: float, equation: str) -> None:
        self.kcal = kcal
        self.equation = equation

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"BMRResult(kcal={self.kcal}, equation={self.equation!r})"


def _mifflin_st_jeor(sex: Sex, kg: float, cm: float, age: int) -> float:
    """Female/male Mifflin; sex-averaged midpoint for other/unspecified."""
    base = 10.0 * kg + 6.25 * cm - 5.0 * age
    if sex == Sex.female:
        return base - 161.0
    if sex == Sex.male:
        return base + 5.0
    # Sex-averaged midpoint: (+5 + -161) / 2 = -78.
    return base - 78.0


def _katch_mcardle(kg: float, body_fat_pct: float) -> float:
    lbm = kg * (1.0 - body_fat_pct / 100.0)
    return 370.0 + 21.6 * lbm


def compute_bmr(
    *,
    sex: Sex,
    kg: float,
    cm: float,
    age: int,
    body_fat_pct: Optional[float],
    rationale: RationaleBuilder,
) -> BMRResult:
    """Compute BMR and append one rationale step.

    Callers must have already verified the inputs are non-None and
    within plausible ranges (SPEC-002 Pydantic validators enforce
    this at the API boundary). This function does not re-validate.
    """
    if body_fat_pct is not None:
        kcal = _katch_mcardle(kg, body_fat_pct)
        rationale.add(
            step_id="bmr_katch_mcardle",
            label="Basal metabolic rate (Katch–McArdle, body-fat aware)",
            inputs={"kg": kg, "body_fat_pct": body_fat_pct},
            outputs={"bmr_kcal": round(kcal, 1)},
            source="Katch & McArdle (1980); Exercise Physiology 8th ed.",
        )
        return BMRResult(kcal=kcal, equation="katch_mcardle")

    kcal = _mifflin_st_jeor(sex, kg, cm, age)
    if sex in (Sex.other, Sex.unspecified):
        note = "sex-averaged midpoint used (sex unspecified)"
    else:
        note = None
    rationale.add(
        step_id=f"bmr_mifflin_{sex.value}",
        label="Basal metabolic rate (Mifflin–St Jeor)",
        inputs={"sex": sex.value, "kg": kg, "cm": cm, "age": age},
        outputs={"bmr_kcal": round(kcal, 1)},
        source="Mifflin et al., Am J Clin Nutr 1990",
        note=note,
    )
    return BMRResult(kcal=kcal, equation=f"mifflin_{sex.value}")
