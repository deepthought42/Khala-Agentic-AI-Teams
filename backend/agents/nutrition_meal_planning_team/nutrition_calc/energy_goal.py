"""Goal-adjusted energy target, with safety floor.

SPEC-003 §4.5. Maps ``(TDEE, GoalsInfo, BiometricInfo)`` to a
``kcal_target`` plus a rationale record of what the deficit /
surplus / floor adjustment did.

Rate-cap safety:
- SPEC-002 clamps ``rate_kg_per_week`` at 1.0 kg.
- This function additionally enforces a per-profile 1% body weight
  per week cap. If the requested rate exceeds this, it is reduced
  and the rationale records the reduction.

Floor safety:
- ``kcal_target = max(kcal_target, max(1200, 0.8 · BMR))``.
- Rationale records when the floor was applied.

Pregnancy / lactation cohorts call into this function **only**
through ``clinical_overrides`` — the default deficit-path here is
skipped entirely for those cohorts (``compute_targets`` short-
circuits based on cohort routing).
"""

from __future__ import annotations

from typing import Optional

from ..models import GoalsInfo
from .rationale import RationaleBuilder

__all__ = ["compute_energy_target", "KCAL_PER_KG_FAT", "ABSOLUTE_KCAL_FLOOR"]

# 7700 kcal ≈ 1 kg of fat mass (historical clinical approximation;
# Wishnofsky 1958 with widely-cited modern refinements). Pinned.
KCAL_PER_KG_FAT = 7700.0

# Non-negotiable absolute kcal floor. Medical literature disagrees on
# the exact number; we pick 1200 as the conservative lower bound used
# widely in consumer apps. A profile whose computed deficit would
# push below this gets clamped to max(1200, 0.8·BMR).
ABSOLUTE_KCAL_FLOOR = 1200.0

# Fraction of BMR below which we refuse to prescribe. Together with
# ABSOLUTE_KCAL_FLOOR, forms the safety floor.
BMR_FLOOR_MULTIPLIER = 0.8


def _per_profile_rate_cap(weight_kg: Optional[float]) -> float:
    """1% of body weight per week, with a sensible floor for missing
    weight.

    When weight is missing we fall back to 1.0 kg/week (same as the
    hard cap in SPEC-002). In practice the cohort router refuses to
    compute at all without weight, so this branch is a safety net.
    """
    if weight_kg is None or weight_kg <= 0:
        return 1.0
    return 0.01 * weight_kg


def compute_energy_target(
    *,
    tdee_kcal: float,
    bmr_kcal: float,
    goals: GoalsInfo,
    weight_kg: Optional[float],
    rationale: RationaleBuilder,
) -> float:
    """Compute kcal/day target. Applies goal delta then safety floor."""
    goal_type = (goals.goal_type or "maintain").lower()
    rate = goals.rate_kg_per_week

    # Rate cap (per-profile 1% body weight / week).
    effective_rate = rate
    if rate is not None and rate > 0:
        cap = _per_profile_rate_cap(weight_kg)
        if rate > cap:
            effective_rate = cap
            rationale.add(
                step_id="rate_capped_by_body_weight",
                label="Requested rate exceeded 1% body weight/week cap",
                inputs={"requested_rate_kg_per_week": rate, "cap_kg_per_week": cap},
                outputs={"effective_rate_kg_per_week": cap},
                source="Safety cap per SPEC-003 §4.5.",
            )

    # Goal delta.
    if goal_type == "lose_weight" and effective_rate:
        delta_kcal = -KCAL_PER_KG_FAT * effective_rate / 7.0
        target = tdee_kcal + delta_kcal
        rationale.add(
            step_id="goal_delta_lose_weight",
            label=f"Deficit for {effective_rate:.2f} kg/week loss",
            inputs={
                "tdee_kcal": round(tdee_kcal, 1),
                "rate_kg_per_week": effective_rate,
                "kcal_per_kg_fat": KCAL_PER_KG_FAT,
            },
            outputs={
                "delta_kcal_per_day": round(delta_kcal, 1),
                "target_kcal_pre_floor": round(target, 1),
            },
            source="7700 kcal ≈ 1 kg fat (Wishnofsky 1958).",
        )
    elif goal_type == "gain_weight" and effective_rate:
        delta_kcal = +KCAL_PER_KG_FAT * effective_rate / 7.0
        target = tdee_kcal + delta_kcal
        rationale.add(
            step_id="goal_delta_gain_weight",
            label=f"Surplus for {effective_rate:.2f} kg/week gain",
            inputs={
                "tdee_kcal": round(tdee_kcal, 1),
                "rate_kg_per_week": effective_rate,
                "kcal_per_kg_fat": KCAL_PER_KG_FAT,
            },
            outputs={
                "delta_kcal_per_day": round(delta_kcal, 1),
                "target_kcal_pre_floor": round(target, 1),
            },
            source="7700 kcal ≈ 1 kg fat (Wishnofsky 1958).",
        )
    elif goal_type == "muscle":
        # Small surplus regardless of rate — lean-gain convention.
        delta_kcal = +250.0
        target = tdee_kcal + delta_kcal
        rationale.add(
            step_id="goal_delta_muscle",
            label="Small surplus for muscle gain",
            inputs={"tdee_kcal": round(tdee_kcal, 1)},
            outputs={
                "delta_kcal_per_day": delta_kcal,
                "target_kcal_pre_floor": round(target, 1),
            },
            source="Phillips & Van Loon, J Sports Sci 2011.",
        )
    else:
        # maintain (or unrecognized goal): TDEE unchanged.
        target = tdee_kcal
        rationale.add(
            step_id="goal_delta_maintain",
            label="Maintenance — no energy delta",
            inputs={"tdee_kcal": round(tdee_kcal, 1)},
            outputs={"target_kcal_pre_floor": round(target, 1)},
            source="SPEC-003 §4.5 maintenance path.",
        )

    # Safety floor.
    floor = max(ABSOLUTE_KCAL_FLOOR, BMR_FLOOR_MULTIPLIER * bmr_kcal)
    if target < floor:
        rationale.add(
            step_id="safety_floor_applied",
            label="kcal target raised to safety floor",
            inputs={
                "proposed_kcal": round(target, 1),
                "absolute_floor": ABSOLUTE_KCAL_FLOOR,
                "bmr_multiplier_floor": round(BMR_FLOOR_MULTIPLIER * bmr_kcal, 1),
            },
            outputs={"target_kcal_post_floor": round(floor, 1)},
            source=(
                f"Floor = max({ABSOLUTE_KCAL_FLOOR}, {BMR_FLOOR_MULTIPLIER}·BMR) per SPEC-003 §4.5."
            ),
        )
        target = floor

    return target
