"""Total Daily Energy Expenditure.

SPEC-003 §4.4. ``TDEE = BMR × PAL`` where the PAL multipliers live
in ``tables/pal.yaml``. No NEAT adjustments, no occupation-specific
multipliers — additional parameters would need inputs we do not
collect, and they would compromise reproducibility.
"""

from __future__ import annotations

from ..models import ActivityLevel
from ._tables import load_table
from .rationale import RationaleBuilder

__all__ = ["compute_tdee"]

_PAL = load_table("pal")


def _pal_value(level: ActivityLevel) -> float:
    try:
        return float(_PAL[level.value])
    except KeyError as exc:
        # pal.yaml is pinned; a missing key is a config bug, not a
        # user-facing error.
        raise RuntimeError(
            f"pal.yaml missing multiplier for activity_level={level.value!r}"
        ) from exc


def compute_tdee(
    *,
    bmr_kcal: float,
    activity_level: ActivityLevel,
    rationale: RationaleBuilder,
) -> float:
    pal = _pal_value(activity_level)
    tdee = bmr_kcal * pal
    rationale.add(
        step_id="tdee_bmr_times_pal",
        label=f"Total daily energy expenditure ({activity_level.value})",
        inputs={"bmr_kcal": round(bmr_kcal, 1), "pal": pal},
        outputs={"tdee_kcal": round(tdee, 1)},
        source="ACSM Guidelines 11th ed.; WHO/FAO/UNU 2004 activity factors.",
    )
    return tdee
