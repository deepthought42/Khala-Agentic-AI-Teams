"""SPEC-006 resolver hook, split out for testing without strands.

Pure logic only. ``agent.py`` imports and applies this after both the
LLM merge and the structural fallback, so tests can exercise it
directly without the strands stack.
"""

from __future__ import annotations

import logging
import os

from ...models import ClientProfile

logger = logging.getLogger(__name__)

_FLAG = "NUTRITION_RESTRICTION_RESOLVER"


def is_resolver_enabled() -> bool:
    """SPEC-006 feature-flag truth source.

    Read at every call site so the env can flip without restarting
    the process. Off by default until the rollout in spec §5 ramps.
    """
    return os.environ.get(_FLAG, "0") == "1"


def apply_resolver(profile: ClientProfile) -> ClientProfile:
    """Populate ``profile.restriction_resolution`` when the SPEC-006
    feature flag is on.

    Mutates the profile in place and returns it. Raw lists are
    untouched. On resolver failure, logs a warning and returns the
    profile with its existing (default) resolution so the user's
    write still persists.
    """
    if not is_resolver_enabled():
        return profile
    try:
        from ...restriction_resolver import resolve_restrictions

        profile.restriction_resolution = resolve_restrictions(
            profile.allergies_and_intolerances or [],
            profile.dietary_needs or [],
        )
    except Exception:
        logger.warning(
            "restriction resolver failed; leaving resolution untouched",
            exc_info=True,
        )
    return profile
