"""Closed clinical taxonomy for the Nutrition & Meal Planning team.

This module defines the canonical sets of medical conditions and
medication classes that downstream components (the calculator in
SPEC-003, the allergen / interaction guardrail in SPEC-007) can
pattern-match on.

The enums are **closed**: additions are a minor version bump, removals
or renames are a major bump. Anything outside the enums lives in the
open ``conditions_freetext`` / ``medications_freetext`` lists on
``ClinicalInfo`` and is surfaced to the LLM narrator as caveat text, but
is never used to drive numeric clamps.

v1 scope is deliberately narrow:

- Conditions: the set for which SPEC-003's ``clinical_overrides.py``
  will ship targeted numeric clamps in v1, plus a small set of common
  comorbidities that the narrator should be aware of but that do not
  yet change numbers.
- Medications: tagged by **class**, not drug name. SPEC-007's
  ``interactions.yaml`` keys on these class tags.

The contents are intentionally short. Keep them that way. New entries
require the team lead's review and, where numeric clamps are added,
the clinical reviewer on SPEC-003 signing off simultaneously.
"""

from __future__ import annotations

from enum import Enum
from typing import FrozenSet

CLINICAL_TAXONOMY_VERSION = "1.0.0"


class Condition(str, Enum):
    """Closed set of medical conditions recognized by the calculator.

    Anything not listed belongs in ``ClinicalInfo.conditions_freetext``.
    """

    ckd_stage_1 = "ckd_stage_1"
    ckd_stage_2 = "ckd_stage_2"
    ckd_stage_3 = "ckd_stage_3"
    ckd_stage_4 = "ckd_stage_4"
    ckd_stage_5 = "ckd_stage_5"
    hypertension = "hypertension"
    t1_diabetes = "t1_diabetes"
    t2_diabetes = "t2_diabetes"
    prediabetes = "prediabetes"
    pcos = "pcos"
    hypothyroid = "hypothyroid"
    hyperthyroid = "hyperthyroid"
    celiac = "celiac"
    ibs = "ibs"
    gerd = "gerd"
    gallstones = "gallstones"
    dyslipidemia = "dyslipidemia"
    gout = "gout"


class Medication(str, Enum):
    """Closed set of medication *classes* (not drug names).

    Keyed by the interaction-relevant class so SPEC-007's guardrail can
    look up forbidden ``InteractionTag`` sets deterministically.
    """

    warfarin = "warfarin"
    maoi = "maoi"
    ssri = "ssri"
    acei_arb = "acei_arb"
    k_sparing_diuretic = "k_sparing_diuretic"
    statin = "statin"
    amiodarone = "amiodarone"
    glp1 = "glp1"
    metformin = "metformin"
    levothyroxine = "levothyroxine"
    lithium = "lithium"
    st_johns_wort = "st_johns_wort"


# Convenience frozensets for membership tests. These are not a source
# of truth — the enums are — but they let callers write
# ``if cond in CKD_STAGES`` without manually listing the members.

CKD_STAGES: FrozenSet[Condition] = frozenset(
    {
        Condition.ckd_stage_1,
        Condition.ckd_stage_2,
        Condition.ckd_stage_3,
        Condition.ckd_stage_4,
        Condition.ckd_stage_5,
    }
)

CLINICIAN_GUIDED_ONLY: FrozenSet[Condition] = frozenset(
    {
        Condition.ckd_stage_4,
        Condition.ckd_stage_5,
    }
)
"""Conditions that SPEC-003's cohort router sends to guidance-only.

The calculator refuses to emit numeric deficit targets for these
cohorts; the agent narrator replaces them with a "please work with
your clinician" response.
"""


DIABETES: FrozenSet[Condition] = frozenset(
    {
        Condition.t1_diabetes,
        Condition.t2_diabetes,
        Condition.prediabetes,
    }
)


def is_known_condition(value: str) -> bool:
    """Return True iff ``value`` is a Condition enum value."""
    return value in Condition._value2member_map_


def is_known_medication(value: str) -> bool:
    """Return True iff ``value`` is a Medication enum value."""
    return value in Medication._value2member_map_


def parse_conditions(values: list[str]) -> tuple[list[Condition], list[str]]:
    """Split a free list into (recognized conditions, unrecognized strings).

    The unrecognized bucket is what lands in ``conditions_freetext``.
    """
    known: list[Condition] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for raw in values:
        s = (raw or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        if is_known_condition(s):
            known.append(Condition(s))
        else:
            unknown.append(s)
    return known, unknown


def parse_medications(values: list[str]) -> tuple[list[Medication], list[str]]:
    """Split a free list into (recognized medications, unrecognized strings)."""
    known: list[Medication] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for raw in values:
        s = (raw or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        if is_known_medication(s):
            known.append(Medication(s))
        else:
            unknown.append(s)
    return known, unknown
