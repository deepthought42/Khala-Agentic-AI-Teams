"""Condition- and reproductive-state-specific clamps, applied last.

SPEC-003 §4.8. Each override is a pure function
``(CalculatorResult-like, RationaleBuilder) -> CalculatorResult-like``
that may:

- Lower a macronutrient target (protein cap for CKD 1-3).
- Lower a micronutrient upper bound (sodium ≤ 1500 mg for HTN).
- Adjust kcal (pregnancy T2/T3, lactation).
- Tag metadata (per-meal carb cap for T2D — consumed by ADR-003).

Overrides chain in a fixed, documented order. If two overrides set
the same field, the stricter value wins and both are recorded in
``applied_overrides``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..clinical_taxonomy import CKD_STAGES, Condition, Medication
from ..models import ClinicalInfo, ReproductiveState
from .macros import MacroAllocation
from .micros import MicroTarget
from .rationale import RationaleBuilder

__all__ = ["apply_clinical_overrides", "ClinicalOverrideState"]


@dataclass
class ClinicalOverrideState:
    """Mutable bundle passed through the override chain.

    The calculator constructs this from its computed macros / micros /
    kcal, lets the chain rewrite values in place, then reads back
    final numbers.
    """

    kcal_target: float
    macros: MacroAllocation
    micros: dict[str, MicroTarget]
    weight_kg: float
    # Free-form metadata the overrides can attach. ADR-003 and SPEC-010
    # look here for per-meal caps and advisory flags.
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Individual overrides (each returns True if it applied; False if no-op).
# ---------------------------------------------------------------------------


def _override_hypertension(
    clinical: ClinicalInfo,
    state: ClinicalOverrideState,
    rationale: RationaleBuilder,
) -> bool:
    if Condition.hypertension.value not in clinical.conditions:
        return False
    # DASH / AHA guidance: sodium ≤ 1500 mg/day for stage 1 HTN.
    sodium = state.micros.get("sodium_mg")
    if sodium is None:
        return False
    prior = sodium.upper
    new_upper = min(1500.0, prior) if prior is not None else 1500.0
    if prior == new_upper:
        return False
    state.micros["sodium_mg"] = MicroTarget(
        name="sodium_mg",
        target=sodium.target,
        upper=new_upper,
        unit=sodium.unit,
        source=f"{sodium.source}; clamped to 1500 mg for hypertension (AHA 2017).",
    )
    rationale.add(
        step_id="hypertension_sodium_cap",
        label="Hypertension: sodium upper cap ≤ 1500 mg/day",
        inputs={"prior_upper_mg": prior},
        outputs={"new_upper_mg": new_upper},
        source="AHA/ACC 2017 hypertension guidelines; DASH diet target.",
    )
    rationale.mark_override("hypertension_sodium_cap")
    return True


def _override_ckd_protein(
    clinical: ClinicalInfo,
    state: ClinicalOverrideState,
    rationale: RationaleBuilder,
) -> bool:
    """CKD stages 1-3: protein cap ≤ 0.8 g/kg (KDIGO 2020 non-dialysis)."""
    has_ckd = any(c in {s.value for s in CKD_STAGES} for c in clinical.conditions)
    if not has_ckd:
        return False
    cap_gpk = 0.8
    cap_g = cap_gpk * state.weight_kg
    if state.macros.protein_g <= cap_g + 0.5:  # rounding tolerance
        return False
    from .macros import KCAL_PER_G_CARBS, KCAL_PER_G_PROTEIN

    prior_protein_g = state.macros.protein_g
    # Freed-up kcal migrate to carbs (simplest rebalance; clinical
    # dietitians can refine per patient).
    freed_kcal = (prior_protein_g - cap_g) * KCAL_PER_G_PROTEIN
    state.macros.protein_g = cap_g
    state.macros.carbs_g += freed_kcal / KCAL_PER_G_CARBS
    rationale.add(
        step_id="ckd_protein_cap",
        label="CKD: protein capped at 0.8 g/kg",
        inputs={
            "prior_protein_g": round(prior_protein_g, 1),
            "cap_g_per_kg": cap_gpk,
            "weight_kg": state.weight_kg,
        },
        outputs={
            "new_protein_g": round(cap_g, 1),
            "carbs_g_after_reallocation": round(state.macros.carbs_g, 1),
        },
        source="KDIGO 2020 clinical practice guideline (non-dialysis CKD).",
    )
    rationale.mark_override("ckd_protein_cap")
    return True


def _override_ckd_phosphorus(
    clinical: ClinicalInfo,
    state: ClinicalOverrideState,
    rationale: RationaleBuilder,
) -> bool:
    """Flag phosphorus for CKD via metadata (no numeric retarget in v1
    — too patient-specific). ADR-005 substitution surfaces the flag."""
    has_ckd = any(c in {s.value for s in CKD_STAGES} for c in clinical.conditions)
    if not has_ckd:
        return False
    state.metadata.setdefault("caution_flags", []).append("phosphorus")
    rationale.add(
        step_id="ckd_phosphorus_caution",
        label="CKD: phosphorus caution flag set (informational)",
        inputs={},
        outputs={"caution_flag": "phosphorus"},
        source="KDIGO 2020 guideline (individualized phosphate management).",
    )
    rationale.mark_override("ckd_phosphorus_caution")
    return True


def _override_t2d_per_meal_carbs(
    clinical: ClinicalInfo,
    state: ClinicalOverrideState,
    rationale: RationaleBuilder,
) -> bool:
    """T2D: add per-meal carb cap metadata (~60 g, 3-meal distribution)."""
    if Condition.t2_diabetes.value not in clinical.conditions:
        return False
    per_meal_g = round(state.macros.carbs_g / 3.0)
    state.metadata["per_meal_carb_cap_g"] = per_meal_g
    rationale.add(
        step_id="t2d_per_meal_carb_cap",
        label=f"T2D: per-meal carb cap ≈ {per_meal_g} g (advisory metadata)",
        inputs={"daily_carbs_g": round(state.macros.carbs_g, 1), "meals_per_day": 3},
        outputs={"per_meal_carb_cap_g": per_meal_g},
        source="ADA Standards of Care 2023 — individualize carb distribution.",
    )
    rationale.mark_override("t2d_per_meal_carb_cap")
    return True


def _override_reproductive_kcal(
    clinical: ClinicalInfo,
    state: ClinicalOverrideState,
    rationale: RationaleBuilder,
) -> bool:
    """Pregnancy T2/T3 and lactation kcal deltas.

    Applied here rather than in energy_goal so the baseline kcal path
    stays cohort-agnostic. Values match SPEC-003 §4.8 / IOM DRI
    energy requirement deltas.
    """
    state_to_delta = {
        ReproductiveState.pregnant_t1: 0,
        ReproductiveState.pregnant_t2: +340,
        ReproductiveState.pregnant_t3: +450,
        ReproductiveState.lactating: +330,
        ReproductiveState.postpartum: 0,
        ReproductiveState.none: 0,
    }
    delta = state_to_delta.get(clinical.reproductive_state, 0)
    if delta == 0:
        return False
    from .macros import KCAL_PER_G_CARBS

    prior_kcal = state.kcal_target
    state.kcal_target = prior_kcal + delta
    # Route the extra kcal into carbs by convention (they provide the
    # glucose drive for pregnancy / lactation energy demand).
    state.macros.carbs_g += delta / KCAL_PER_G_CARBS
    rationale.add(
        step_id=f"reproductive_kcal_{clinical.reproductive_state.value}",
        label=f"Reproductive state: {clinical.reproductive_state.value} kcal delta",
        inputs={"prior_kcal": round(prior_kcal, 1)},
        outputs={
            "delta_kcal": delta,
            "new_kcal": round(state.kcal_target, 1),
            "carbs_g": round(state.macros.carbs_g, 1),
        },
        source="IOM DRI energy requirements; pregnancy/lactation additions.",
    )
    rationale.mark_override(f"reproductive_kcal_{clinical.reproductive_state.value}")
    return True


def _override_warfarin_vitamin_k_note(
    clinical: ClinicalInfo,
    state: ClinicalOverrideState,
    rationale: RationaleBuilder,
) -> bool:
    """Advisory metadata only. SPEC-007 guardrail is where the
    per-ingredient enforcement lives; here we just tag the plan so
    the narrator can surface the "coordinate with INR" note."""
    if Medication.warfarin.value not in clinical.medications:
        return False
    state.metadata.setdefault("advisory_notes", []).append("warfarin_vitamin_k")
    rationale.add(
        step_id="warfarin_vitamin_k_advisory",
        label="Warfarin: vitamin-K consistency advisory",
        inputs={},
        outputs={"advisory": "warfarin_vitamin_k"},
        source=("Holbrook et al., Chest 2012 — consistent vitamin-K intake with INR monitoring."),
    )
    rationale.mark_override("warfarin_vitamin_k_advisory")
    return True


# Fixed application order. Sodium / protein caps run before T2D carb
# metadata because their changes affect the carb redistribution math.
ORDER = (
    _override_hypertension,
    _override_ckd_protein,
    _override_ckd_phosphorus,
    _override_reproductive_kcal,
    _override_t2d_per_meal_carbs,
    _override_warfarin_vitamin_k_note,
)


def apply_clinical_overrides(
    *,
    clinical: Optional[ClinicalInfo],
    state: ClinicalOverrideState,
    rationale: RationaleBuilder,
) -> ClinicalOverrideState:
    if clinical is None:
        return state
    for override in ORDER:
        override(clinical, state, rationale)
    return state
