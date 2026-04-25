"""SPEC-007 §4.4 step 3 — dietary rejection.

Spec §6.1: vegan + milk → reject; pescatarian + chicken → reject;
pescatarian + fish → pass.
"""

from __future__ import annotations

from agents.nutrition_meal_planning_team.guardrail import (
    Severity,
    ViolationReason,
    check_recommendation,
)
from agents.nutrition_meal_planning_team.ingredient_kb.taxonomy import DietaryTag
from agents.nutrition_meal_planning_team.models import ResolvedRestriction

from ._fixtures import profile_from_resolver, profile_with, recipe


def test_vegan_rejects_milk() -> None:
    profile = profile_with(dietary_forbid=[DietaryTag.animal, DietaryTag.dairy])
    rec = recipe("milk")

    result = check_recommendation(profile, rec)

    assert result.passed is False
    dietary = [v for v in result.violations if v.reason is ViolationReason.dietary_forbid]
    assert dietary, "expected a dietary_forbid violation"
    assert all(v.severity is Severity.hard_reject for v in dietary)
    assert {v.tag for v in dietary} == {"animal", "dairy"}


def test_pescatarian_rejects_chicken() -> None:
    """Pescatarian = forbid `animal` but exempt `fish`. The catalog
    tags chicken with ``dietary_tags=[animal]`` (no fish), so a
    pescatarian profile (forbid `animal`) hard-rejects chicken."""
    profile = profile_with(dietary_forbid=[DietaryTag.animal])
    rec = recipe("chicken thigh")

    result = check_recommendation(profile, rec)

    assert result.passed is False
    dietary = [v for v in result.violations if v.reason is ViolationReason.dietary_forbid]
    assert any(v.tag == "animal" for v in dietary)


def test_pescatarian_passes_fish() -> None:
    """Sanity baseline: with no active dietary forbid set, salmon
    naturally passes. Kept alongside the resolver-driven regression
    test below as the pre-#351 sidestepped version."""
    profile = profile_with(dietary_forbid=[])
    rec = recipe("salmon")

    result = check_recommendation(profile, rec)

    assert result.passed is True


def test_honey_forbidden_for_vegan() -> None:
    """SPEC-007 red-team: honey on a vegan profile must reject."""
    profile = profile_with(dietary_forbid=[DietaryTag.honey, DietaryTag.animal])
    rec = recipe("honey")

    result = check_recommendation(profile, rec)

    assert result.passed is False
    tags = {v.tag for v in result.violations}
    assert "honey" in tags
    assert "animal" in tags


def test_pescatarian_resolution_passes_fish() -> None:
    """Issue #351 regression pin: salmon must pass under a
    pescatarian-shorthand-resolved profile.

    Goes through the real resolver so the pescatarian
    ``dietary_allergen_exemptions=[fish, shellfish]`` is attached. The
    checker's per-food ``applicable_dietary_forbid`` then drops the
    ``animal`` forbid for salmon (allergen ``fish``)."""
    profile = profile_from_resolver(dietary_needs=["pescatarian"])
    rec = recipe("salmon")

    result = check_recommendation(profile, rec)

    assert result.passed is True


def test_pescatarian_still_rejects_chicken_via_resolution() -> None:
    """Pescatarian's exemption is allergen-keyed: chicken has no
    ``fish``/``shellfish`` allergen tag, so the ``animal`` forbid still
    applies. Confirms the exemption does not trivialise the rule."""
    profile = profile_from_resolver(dietary_needs=["pescatarian"])
    rec = recipe("chicken thigh")

    result = check_recommendation(profile, rec)

    assert result.passed is False
    dietary = [v for v in result.violations if v.reason is ViolationReason.dietary_forbid]
    assert any(v.tag == "animal" for v in dietary)


def test_explicit_animal_forbid_without_pescatarian_rejects_salmon() -> None:
    """Exemptions only apply when the resolver attached them. A user
    who manually says ``forbid_dietary=[animal]`` (no pescatarian
    shorthand) gets the unconditional rule — salmon still rejects."""
    profile = profile_with(dietary_forbid=[DietaryTag.animal])
    rec = recipe("salmon")

    result = check_recommendation(profile, rec)

    assert result.passed is False
    dietary = [v for v in result.violations if v.reason is ViolationReason.dietary_forbid]
    assert any(v.tag == "animal" for v in dietary)


def test_pescatarian_plus_separate_animal_forbid_rejects_salmon() -> None:
    """Exemptions are per-``ResolvedRestriction``: a second row
    forbidding ``animal`` without exemptions still triggers, even when
    pescatarian is also resolved. Models a user who typed both
    "pescatarian" and "no animal"."""
    profile = profile_from_resolver(
        dietary_needs=["pescatarian"],
        extra_resolved=[
            ResolvedRestriction(
                raw="no-animal",
                dietary_tags_forbid=[DietaryTag.animal],
            )
        ],
    )
    rec = recipe("salmon")

    result = check_recommendation(profile, rec)

    assert result.passed is False
    dietary = [v for v in result.violations if v.reason is ViolationReason.dietary_forbid]
    assert any(v.tag == "animal" for v in dietary)
    assert all(v.severity is Severity.hard_reject for v in dietary)


def test_no_dietary_forbid_passes_anything() -> None:
    profile = profile_with(dietary_forbid=[])
    rec = recipe("milk", "egg", "chicken thigh", "salmon")

    result = check_recommendation(profile, rec)

    assert result.passed is True
    assert result.violations == ()
