"""Micronutrient target lookup against the DRI table.

SPEC-003 §4.7. Looks up ``(sex, age_band, reproductive_state)`` in
``tables/dri.yaml`` for the v1 micro set: fiber, sodium (upper only),
potassium, calcium, iron, vitamin D, B12, phosphorus, vitamin K.

Reproductive-state deltas are applied by ``clinical_overrides`` so
this module stays lookup-only.
"""

from __future__ import annotations

from typing import Optional

from ..models import ReproductiveState, Sex
from ._tables import load_table
from .rationale import RationaleBuilder

__all__ = ["compute_micros", "MicroTarget", "V1_MICRO_NUTRIENTS", "age_band_for"]

_DRI = load_table("dri")

# Closed list of micros v1 emits. Additions bump CALCULATOR_VERSION
# minor. Downstream consumers (ADR-003 rollup; ADR-006 adherence)
# enumerate against this list.
V1_MICRO_NUTRIENTS: tuple[str, ...] = (
    "fiber_g",
    "sodium_mg",
    "potassium_mg",
    "calcium_mg",
    "iron_mg",
    "vitamin_d_mcg",
    "vitamin_b12_mcg",
    "phosphorus_mg",
    "vitamin_k_mcg",
)


class MicroTarget:
    """Structured per-nutrient target record.

    Stored on ``CalculatorResult.micros`` so the UI and ADR-003
    rollup can reason about both lower targets and upper limits
    uniformly.
    """

    __slots__ = ("name", "target", "upper", "unit", "source")

    def __init__(
        self,
        name: str,
        *,
        target: Optional[float],
        upper: Optional[float],
        unit: str,
        source: str,
    ) -> None:
        self.name = name
        self.target = target
        self.upper = upper
        self.unit = unit
        self.source = source

    def as_dict(self) -> dict:
        return {
            "target": self.target,
            "upper": self.upper,
            "unit": self.unit,
            "source": self.source,
        }


def age_band_for(age_years: int) -> str:
    """Map adult age → DRI age-band label. 2–18 is handled by the
    minor cohort router; here we defensively clamp at 19_30 so a
    downstream bug does not produce a KeyError — the cohort router
    is the actual guard."""
    if age_years < 19:
        return "19_30"
    if age_years <= 30:
        return "19_30"
    if age_years <= 50:
        return "31_50"
    if age_years <= 70:
        return "51_70"
    return "71_plus"


def _unit_for(nutrient: str) -> str:
    # Unit is encoded in the nutrient name suffix (_g, _mg, _mcg).
    for suffix, unit in (("_mg", "mg"), ("_mcg", "mcg"), ("_g", "g")):
        if nutrient.endswith(suffix):
            return unit
    return ""


def _lookup_sex_key(sex: Sex) -> str:
    """Map Sex → DRI row. ``other`` / ``unspecified`` routes to the
    lower-RDA side (female) for iron/fiber when life stage allows,
    which is the more conservative choice for the consumer-health
    framing (leaves more headroom; avoids over-prescribing iron)."""
    if sex == Sex.male:
        return "male"
    return "female"


def compute_micros(
    *,
    sex: Sex,
    age_years: int,
    reproductive_state: ReproductiveState,
    rationale: RationaleBuilder,
) -> dict[str, MicroTarget]:
    sex_key = _lookup_sex_key(sex)
    band = age_band_for(age_years)

    out: dict[str, MicroTarget] = {}
    missing: list[str] = []
    for nutrient in V1_MICRO_NUTRIENTS:
        table = _DRI.get(nutrient)
        if not table:
            missing.append(nutrient)
            continue
        row = table.get(sex_key, {}).get(band)
        if not row:
            missing.append(nutrient)
            continue
        out[nutrient] = MicroTarget(
            name=nutrient,
            target=row.get("target"),
            upper=row.get("upper"),
            unit=_unit_for(nutrient),
            source=row.get("source", "DRI"),
        )

    # Reproductive deltas applied here (pre-clinical-overrides so the
    # downstream override layer sees the already-adjusted targets).
    deltas_table = _DRI.get("reproductive_deltas", {})
    repro_deltas = deltas_table.get(reproductive_state.value, {}) or {}
    applied_repro: dict[str, float] = {}
    for nutrient, delta in repro_deltas.items():
        if nutrient not in out:
            continue
        mt = out[nutrient]
        if mt.target is None:
            continue
        new_target = mt.target + float(delta)
        out[nutrient] = MicroTarget(
            name=nutrient,
            target=new_target,
            upper=mt.upper,
            unit=mt.unit,
            source=f"{mt.source} + reproductive delta {delta:+g}",
        )
        applied_repro[nutrient] = float(delta)

    rationale.add(
        step_id="micros_from_dri",
        label=f"Micronutrient targets (DRI {sex_key}, {band})",
        inputs={
            "sex": sex.value,
            "sex_key": sex_key,
            "age_band": band,
            "reproductive_state": reproductive_state.value,
        },
        outputs={
            "nutrients": {n: mt.as_dict() for n, mt in out.items()},
            "reproductive_deltas_applied": applied_repro,
        },
        source="IOM / NAM DRI summary tables 1997-2019; cited per-row in dri.yaml.",
        note=(f"missing DRI entries: {missing}" if missing else None),
    )
    return out
