"""Lightweight helpers for building ClientProfile + MealRecommendation
fixtures in guardrail unit tests.
"""

from __future__ import annotations

from typing import Iterable

from agents.nutrition_meal_planning_team.ingredient_kb.taxonomy import (
    AllergenTag,
    DietaryTag,
)
from agents.nutrition_meal_planning_team.models import (
    ClientProfile,
    MealRecommendation,
    ResolvedRestriction,
    RestrictionResolution,
)
from agents.nutrition_meal_planning_team.restriction_resolver import (
    resolve_restrictions,
)


def profile_with(
    *,
    allergens: Iterable[AllergenTag] = (),
    dietary_forbid: Iterable[DietaryTag] = (),
    client_id: str = "test_client",
) -> ClientProfile:
    """Build a ClientProfile with the given active tags via SPEC-006
    ``RestrictionResolution.resolved`` entries."""
    resolved: list[ResolvedRestriction] = []
    for tag in allergens:
        resolved.append(
            ResolvedRestriction(
                raw=tag.value,
                allergen_tags=[tag],
            )
        )
    for tag in dietary_forbid:
        resolved.append(
            ResolvedRestriction(
                raw=tag.value,
                dietary_tags_forbid=[tag],
            )
        )
    return ClientProfile(
        client_id=client_id,
        restriction_resolution=RestrictionResolution(resolved=resolved),
    )


def profile_from_resolver(
    *,
    allergies: Iterable[str] = (),
    dietary_needs: Iterable[str] = (),
    extra_resolved: Iterable[ResolvedRestriction] = (),
    client_id: str = "test_client",
) -> ClientProfile:
    """Build a ClientProfile via the real SPEC-006 resolver cascade.

    Use this when the test depends on resolver-attached metadata
    (e.g. ``dietary_allergen_exemptions`` from the pescatarian shorthand,
    issue #351). ``extra_resolved`` lets a test append manually-built
    rows alongside the resolver output to model "user typed pescatarian
    AND no animal" combinations.
    """
    rr = resolve_restrictions(list(allergies), list(dietary_needs))
    if extra_resolved:
        rr = rr.model_copy(update={"resolved": list(rr.resolved) + list(extra_resolved)})
    return ClientProfile(client_id=client_id, restriction_resolution=rr)


def recipe(*ingredients: str, name: str = "test recipe") -> MealRecommendation:
    return MealRecommendation(name=name, ingredients=list(ingredients))
