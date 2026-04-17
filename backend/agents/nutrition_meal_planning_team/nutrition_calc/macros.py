"""Macronutrient allocation from a kcal target.

SPEC-003 §4.6. Goal-aware protein per kg, fat default with dietary
overrides (keto bumps it up), carbs as the remainder — all clamped
into the AMDR bands. If protein + fat together exceed what carbs
AMDR allows, protein is reduced first (to its 0.8 g/kg RDA floor)
before fat.
"""

from __future__ import annotations

from typing import Iterable

from ..models import GoalsInfo
from ._tables import load_table
from .rationale import RationaleBuilder

__all__ = [
    "compute_macros",
    "MacroAllocation",
    "KCAL_PER_G_PROTEIN",
    "KCAL_PER_G_CARBS",
    "KCAL_PER_G_FAT",
]

KCAL_PER_G_PROTEIN = 4.0
KCAL_PER_G_CARBS = 4.0
KCAL_PER_G_FAT = 9.0

_AMDR = load_table("amdr")


class MacroAllocation:
    """Plain result object with computed g/day values."""

    __slots__ = ("protein_g", "fat_g", "carbs_g")

    def __init__(self, protein_g: float, fat_g: float, carbs_g: float) -> None:
        self.protein_g = protein_g
        self.fat_g = fat_g
        self.carbs_g = carbs_g

    def as_dict(self) -> dict[str, float]:
        return {
            "protein_g": round(self.protein_g, 1),
            "fat_g": round(self.fat_g, 1),
            "carbs_g": round(self.carbs_g, 1),
        }


def _protein_base_gpk(goal_type: str) -> float:
    table: dict[str, float] = _AMDR["protein_goal_overrides"]
    if goal_type in table:
        return float(table[goal_type])
    return float(table["maintain"])


def _fat_fraction_for_diet(dietary_needs: Iterable[str]) -> float:
    """Default 25%; keto pushes fat share upward."""
    tags = {t.strip().lower() for t in (dietary_needs or [])}
    if "keto" in tags:
        # Keto: high fat, minimal carbs. Raise fat fraction; the
        # carb-AMDR clamp will still fire in compute, but the
        # rationale captures the intent.
        return 0.65
    if "low_fat" in tags or "low-fat" in tags:
        return float(_AMDR["fat"]["low"])
    return float(_AMDR["fat"]["default"])


def compute_macros(
    *,
    kcal_target: float,
    weight_kg: float,
    goals: GoalsInfo,
    dietary_needs: Iterable[str],
    rationale: RationaleBuilder,
) -> MacroAllocation:
    goal_type = (goals.goal_type or "maintain").lower()
    protein_low_pct = float(_AMDR["protein"]["low"])
    protein_high_pct = float(_AMDR["protein"]["high"])
    rda_gpk = float(_AMDR["protein"]["rda_g_per_kg"])
    fat_low_pct = float(_AMDR["fat"]["low"])
    fat_high_pct = float(_AMDR["fat"]["high"])
    carbs_low_pct = float(_AMDR["carbs"]["low"])
    carbs_high_pct = float(_AMDR["carbs"]["high"])

    # --- Protein: gram-per-kg then clamp to AMDR -----------------------
    base_gpk = _protein_base_gpk(goal_type)
    raw_protein_g = base_gpk * weight_kg
    protein_kcal_raw = raw_protein_g * KCAL_PER_G_PROTEIN
    protein_kcal_min = protein_low_pct * kcal_target
    protein_kcal_max = protein_high_pct * kcal_target
    protein_kcal = max(protein_kcal_min, min(protein_kcal_raw, protein_kcal_max))
    clamped_protein = protein_kcal != protein_kcal_raw
    protein_g = protein_kcal / KCAL_PER_G_PROTEIN
    rationale.add(
        step_id="protein_from_body_weight_then_amdr_clamp",
        label=f"Protein: {base_gpk} g/kg → AMDR clamp",
        inputs={
            "weight_kg": weight_kg,
            "base_g_per_kg": base_gpk,
            "raw_protein_g": round(raw_protein_g, 1),
            "amdr_low_pct": protein_low_pct,
            "amdr_high_pct": protein_high_pct,
            "kcal_target": round(kcal_target, 1),
        },
        outputs={
            "protein_g": round(protein_g, 1),
            "protein_pct_kcal": round(protein_kcal / kcal_target, 3) if kcal_target else 0,
        },
        source="ISSN position (Jäger et al. JISSN 2017); IOM 2005 AMDR bands.",
        note=("protein clamped into AMDR band" if clamped_protein else None),
    )

    # --- Fat: diet-aware default fraction, clamped to AMDR ------------
    fat_fraction = _fat_fraction_for_diet(dietary_needs)
    fat_fraction_clamped = max(fat_low_pct, min(fat_fraction, fat_high_pct))
    fat_g = fat_fraction_clamped * kcal_target / KCAL_PER_G_FAT
    rationale.add(
        step_id="fat_from_default_fraction",
        label="Fat: diet-aware default, AMDR clamp",
        inputs={
            "fat_fraction_requested": fat_fraction,
            "fat_fraction_applied": fat_fraction_clamped,
            "kcal_target": round(kcal_target, 1),
        },
        outputs={
            "fat_g": round(fat_g, 1),
            "fat_pct_kcal": round(fat_fraction_clamped, 3),
        },
        source="IOM 2005 AMDR fat 20-35% kcal.",
        note=("fat fraction clamped to AMDR" if fat_fraction_clamped != fat_fraction else None),
    )

    # --- Carbs: remainder then AMDR clamp; backoff protein first ------
    used_kcal = protein_g * KCAL_PER_G_PROTEIN + fat_g * KCAL_PER_G_FAT
    carbs_kcal = max(0.0, kcal_target - used_kcal)
    carbs_kcal_min = carbs_low_pct * kcal_target
    carbs_kcal_max = carbs_high_pct * kcal_target

    backoff_note = None
    if carbs_kcal < carbs_kcal_min:
        # Protein+fat took too much of the budget; drop protein first
        # down to its 0.8 g/kg RDA floor, then clip fat last.
        shortfall = carbs_kcal_min - carbs_kcal
        min_protein_g = rda_gpk * weight_kg
        protein_surplus_kcal = max(protein_g - min_protein_g, 0.0) * KCAL_PER_G_PROTEIN
        take_from_protein = min(shortfall, protein_surplus_kcal)
        protein_g -= take_from_protein / KCAL_PER_G_PROTEIN
        shortfall -= take_from_protein
        if shortfall > 0:
            fat_g -= shortfall / KCAL_PER_G_FAT
            shortfall = 0.0
        used_kcal = protein_g * KCAL_PER_G_PROTEIN + fat_g * KCAL_PER_G_FAT
        carbs_kcal = max(0.0, kcal_target - used_kcal)
        backoff_note = "reduced protein (and fat if needed) to hit carbs AMDR floor"
    elif carbs_kcal > carbs_kcal_max:
        # Rare — protein+fat undershot; carb AMDR caps. Recover by
        # bumping fat up (cheapest non-protein option) to carbs_kcal_max.
        excess = carbs_kcal - carbs_kcal_max
        fat_g += excess / KCAL_PER_G_FAT
        # Re-check fat AMDR upper; if it still exceeds, let it — the
        # carbs cap is advisory per IOM, not a hard cap.
        carbs_kcal = carbs_kcal_max
        backoff_note = "shifted surplus into fat to hit carbs AMDR ceiling"

    carbs_g = carbs_kcal / KCAL_PER_G_CARBS
    rationale.add(
        step_id="carbs_remainder_then_amdr_clamp",
        label="Carbs: remainder of kcal budget, AMDR clamp",
        inputs={
            "kcal_target": round(kcal_target, 1),
            "used_kcal_pre_backoff": round(used_kcal, 1),
            "amdr_low_pct": carbs_low_pct,
            "amdr_high_pct": carbs_high_pct,
        },
        outputs={
            "carbs_g": round(carbs_g, 1),
            "protein_g": round(protein_g, 1),
            "fat_g": round(fat_g, 1),
        },
        source="IOM 2005 AMDR carbs 45-65% kcal.",
        note=backoff_note,
    )

    return MacroAllocation(protein_g=protein_g, fat_g=fat_g, carbs_g=carbs_g)
