"""Unit conversions for user-entered biometric values.

The intake pipeline accepts height in either cm or ft/in, and weight in
either kg or lb. The profile schema (SPEC-002) stores canonical units
only — cm and kg — so values entered in other units are converted at
the API boundary before validation.

These are pure, deterministic functions with no I/O. They are exercised
by both the intake agent (SPEC-002 W4) and the UI unit toggle
(SPEC-002 W9).

No silent failures: malformed input returns ``None``; it does **not**
fall back to zero or the identity conversion.
"""

from __future__ import annotations

from typing import Optional

# Canonical conversion constants — frozen values, not configurable.
INCH_PER_FOOT = 12
CM_PER_INCH = 2.54
KG_PER_LB = 0.45359237


def inches_to_cm(inches: float) -> float:
    """Convert inches → cm. Deterministic, exact to 10 decimal places."""
    return inches * CM_PER_INCH


def ft_in_to_cm(feet: float, inches: float) -> float:
    """Convert feet + inches → cm. Both args are coerced via float()."""
    total_inches = feet * INCH_PER_FOOT + inches
    return inches_to_cm(total_inches)


def cm_to_ft_in(cm: float) -> tuple[int, float]:
    """Convert cm → (feet, remainder_inches). Inches preserve fractional part."""
    total_inches = cm / CM_PER_INCH
    feet = int(total_inches // INCH_PER_FOOT)
    inches = total_inches - feet * INCH_PER_FOOT
    return feet, inches


def lb_to_kg(lb: float) -> float:
    """Convert pounds → kilograms (exact constant)."""
    return lb * KG_PER_LB


def kg_to_lb(kg: float) -> float:
    """Convert kilograms → pounds."""
    return kg / KG_PER_LB


def coerce_height_cm(
    height_cm: Optional[float] = None,
    height_ft: Optional[float] = None,
    height_in: Optional[float] = None,
) -> Optional[float]:
    """Coerce any of the provided height inputs to cm.

    Rules:
    - If ``height_cm`` is provided and non-zero, it wins (user is
      explicit about canonical units).
    - Else if ``height_ft`` or ``height_in`` is provided, treat zero for
      the other as 0 (``5 ft 10 in``, ``6 ft 0 in``, ``0 ft 70 in``).
    - Else return None (no height given).

    Returns ``None`` if the inputs are all None or numerically empty.
    Never returns 0.0 as a sentinel for "missing".
    """
    if height_cm is not None and float(height_cm) > 0:
        return float(height_cm)
    if height_ft is not None or height_in is not None:
        ft = float(height_ft) if height_ft is not None else 0.0
        inches = float(height_in) if height_in is not None else 0.0
        if ft == 0.0 and inches == 0.0:
            return None
        return ft_in_to_cm(ft, inches)
    return None


def coerce_weight_kg(
    weight_kg: Optional[float] = None,
    weight_lb: Optional[float] = None,
) -> Optional[float]:
    """Coerce provided weight input to kg. ``weight_kg`` takes precedence."""
    if weight_kg is not None and float(weight_kg) > 0:
        return float(weight_kg)
    if weight_lb is not None and float(weight_lb) > 0:
        return lb_to_kg(float(weight_lb))
    return None
