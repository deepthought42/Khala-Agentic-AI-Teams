"""Top-level orchestration: profile → CalculatorResult.

SPEC-003 §4.2 / §4.9. Routes the profile to a cohort, runs the
bmr → tdee → energy_goal → macros → micros → clinical_overrides
chain, and assembles a frozen ``CalculatorResult``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..clinical_taxonomy import CLINICIAN_GUIDED_ONLY
from ..models import ClientProfile, DailyTargets, ReproductiveState, Sex
from .bmr import compute_bmr
from .clinical_overrides import ClinicalOverrideState, apply_clinical_overrides
from .energy_goal import compute_energy_target
from .errors import (
    InsufficientInputError,
    UnsupportedCohortError,
)
from .macros import compute_macros
from .micros import MicroTarget, compute_micros
from .rationale import Rationale, RationaleBuilder
from .tdee import compute_tdee
from .version import CALCULATOR_VERSION

__all__ = ["compute_daily_targets", "CalculatorResult", "Cohort"]


class Cohort:
    """String constants for the five cohorts v1 routes to.

    Kept as a plain class of constants (rather than an Enum) so the
    values can be embedded in error payloads that cross module
    boundaries without enum serialization gymnastics.
    """

    GENERAL_ADULT = "general_adult"
    GENERAL_ADULT_SEX_UNSPECIFIED = "general_adult_sex_unspecified"
    PREGNANCY_LACTATION = "pregnancy_lactation"
    ED_ADJACENT = "ed_adjacent"
    MINOR = "minor"
    CLINICIAN_GUIDED = "clinician_guided"


@dataclass(frozen=True)
class CalculatorResult:
    targets: DailyTargets
    rationale: Rationale
    calculator_version: str
    cohort: str
    micros: dict[str, dict]  # serialized MicroTarget.as_dict per nutrient
    intermediates: dict[str, float] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _route_cohort(profile: ClientProfile) -> str:
    """Map a profile to one of five cohorts; raise for the two
    unsupported ones. See SPEC-003 §4.9 flowchart."""
    bio = profile.biometrics
    clin = profile.clinical
    if bio.age_years is not None and bio.age_years < 18:
        raise UnsupportedCohortError(
            cohort=Cohort.MINOR,
            guidance_key="minor",
            clinician_note=(
                "For growing users we focus on variety and balance rather "
                "than calorie targets. Please work with a pediatrician or "
                "registered dietitian for personalized guidance."
            ),
        )
    if clin and any(c in {x.value for x in CLINICIAN_GUIDED_ONLY} for c in clin.conditions):
        # Pick the first clinician-guided tag for the error payload
        # so the narrator can reference it specifically.
        key = next(
            (c for c in clin.conditions if c in {x.value for x in CLINICIAN_GUIDED_ONLY}),
            "clinician_guided",
        )
        raise UnsupportedCohortError(
            cohort=Cohort.CLINICIAN_GUIDED,
            guidance_key=key,
            clinician_note=(
                "Your profile includes a condition that needs individualized "
                "dietitian- or clinician-led planning. We can offer general "
                "food-group guidance; please do not use any specific numeric "
                "targets without your care team."
            ),
        )
    if clin and clin.reproductive_state in (
        ReproductiveState.pregnant_t1,
        ReproductiveState.pregnant_t2,
        ReproductiveState.pregnant_t3,
        ReproductiveState.lactating,
    ):
        return Cohort.PREGNANCY_LACTATION
    if clin and clin.ed_history_flag:
        return Cohort.ED_ADJACENT
    if bio.sex in (Sex.other, Sex.unspecified) and bio.body_fat_pct is None:
        return Cohort.GENERAL_ADULT_SEX_UNSPECIFIED
    return Cohort.GENERAL_ADULT


def _check_required_inputs(profile: ClientProfile, cohort: str) -> None:
    """Required biometric fields check.

    Sex is required for the standard general_adult path (determines
    Mifflin variant). It is NOT required when:
    - cohort is GENERAL_ADULT_SEX_UNSPECIFIED (that IS the sex-
      unspecified branch), or
    - ``body_fat_pct`` is present (Katch-McArdle is sex-independent).

    Age, height, and weight are always required because every
    equation in the pipeline consumes them.
    """
    missing: list[str] = []
    bio = profile.biometrics
    sex_required = cohort != Cohort.GENERAL_ADULT_SEX_UNSPECIFIED and bio.body_fat_pct is None
    if sex_required and bio.sex == Sex.unspecified:
        missing.append("sex")
    if bio.age_years is None:
        missing.append("age_years")
    if bio.height_cm is None:
        missing.append("height_cm")
    if bio.weight_kg is None:
        missing.append("weight_kg")
    if missing:
        raise InsufficientInputError(
            fields=tuple(missing),
            cohort=cohort,
            message=f"missing required biometric fields: {missing}",
        )


def compute_daily_targets(profile: ClientProfile) -> CalculatorResult:
    """Top-level entry point. See SPEC-003 §4.2.

    Raises:
        UnsupportedCohortError: minor / clinician-guided-only cohorts.
        InsufficientInputError: missing required biometric(s).
    """
    cohort = _route_cohort(profile)
    _check_required_inputs(profile, cohort)

    bio = profile.biometrics
    goals = profile.goals
    clinical = profile.clinical
    rationale = RationaleBuilder()

    # --- BMR + TDEE -------------------------------------------------
    bmr = compute_bmr(
        sex=bio.sex,
        kg=bio.weight_kg,  # type: ignore[arg-type]
        cm=bio.height_cm,  # type: ignore[arg-type]
        age=bio.age_years,  # type: ignore[arg-type]
        body_fat_pct=bio.body_fat_pct,
        rationale=rationale,
    )
    tdee_kcal = compute_tdee(
        bmr_kcal=bmr.kcal,
        activity_level=bio.activity_level,
        rationale=rationale,
    )

    # --- Energy goal (cohort-aware) ---------------------------------
    if cohort in (Cohort.PREGNANCY_LACTATION, Cohort.ED_ADJACENT):
        # Pregnancy / lactation: skip the deficit path; clinical
        # overrides add trimester / lactation kcal deltas downstream.
        # ED-adjacent: never prescribe a deficit — kcal target = TDEE.
        kcal_target = tdee_kcal
        rationale.add(
            step_id=f"energy_goal_skipped_{cohort}",
            label=f"Cohort {cohort}: maintenance only, no deficit path",
            inputs={"tdee_kcal": round(tdee_kcal, 1)},
            outputs={"kcal_target": round(kcal_target, 1)},
            source="SPEC-003 §4.9 cohort router.",
        )
    else:
        kcal_target = compute_energy_target(
            tdee_kcal=tdee_kcal,
            bmr_kcal=bmr.kcal,
            goals=goals,
            weight_kg=bio.weight_kg,
            rationale=rationale,
        )

    # --- Macros ------------------------------------------------------
    # ED-adjacent cohort: use maintenance goal regardless of what the
    # profile says, to sidestep accidentally-aggressive protein/fat
    # ratios keyed on "lose_weight".
    if cohort == Cohort.ED_ADJACENT:
        from ..models import GoalsInfo

        effective_goals = GoalsInfo(goal_type="maintain")
    else:
        effective_goals = goals
    macros = compute_macros(
        kcal_target=kcal_target,
        weight_kg=bio.weight_kg,  # type: ignore[arg-type]
        goals=effective_goals,
        dietary_needs=profile.dietary_needs,
        rationale=rationale,
    )

    # --- Micros ------------------------------------------------------
    micros = compute_micros(
        sex=bio.sex,
        age_years=bio.age_years,  # type: ignore[arg-type]
        reproductive_state=clinical.reproductive_state if clinical else ReproductiveState.none,
        rationale=rationale,
    )

    # --- Clinical overrides -----------------------------------------
    override_state = ClinicalOverrideState(
        kcal_target=kcal_target,
        macros=macros,
        micros=micros,
        weight_kg=bio.weight_kg,  # type: ignore[arg-type]
    )
    apply_clinical_overrides(clinical=clinical, state=override_state, rationale=rationale)

    # --- Pack result ------------------------------------------------
    sodium_upper = _upper(override_state.micros, "sodium_mg")
    targets = DailyTargets(
        calories_kcal=round(override_state.kcal_target, 1),
        protein_g=round(override_state.macros.protein_g, 1),
        carbs_g=round(override_state.macros.carbs_g, 1),
        fat_g=round(override_state.macros.fat_g, 1),
        fiber_g=_target(override_state.micros, "fiber_g"),
        sodium_mg=sodium_upper,
        other_nutrients={
            n: _target(override_state.micros, n)
            for n in override_state.micros
            if n not in ("fiber_g", "sodium_mg") and _target(override_state.micros, n) is not None
        },
    )

    intermediates = {
        "bmr_kcal": round(bmr.kcal, 1),
        "tdee_kcal": round(tdee_kcal, 1),
    }

    return CalculatorResult(
        targets=targets,
        rationale=rationale.build(cohort=cohort),
        calculator_version=CALCULATOR_VERSION,
        cohort=cohort,
        micros={n: mt.as_dict() for n, mt in override_state.micros.items()},
        intermediates=intermediates,
        metadata=override_state.metadata,
    )


def _target(micros: dict[str, MicroTarget], key: str) -> float | None:
    mt = micros.get(key)
    return mt.target if mt is not None else None


def _upper(micros: dict[str, MicroTarget], key: str) -> float | None:
    mt = micros.get(key)
    return mt.upper if mt is not None else None
