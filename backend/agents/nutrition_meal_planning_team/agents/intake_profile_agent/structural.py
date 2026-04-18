"""Structural profile merge used as the intake-agent fallback.

Pure logic with no LLM / strands / Postgres dependencies. Lives in its
own module so unit tests can import it without dragging in the
``strands`` stack that ``agent.py`` needs for the primary LLM path.

SPEC-002 extends this to handle the ``biometrics`` and ``clinical``
sub-objects alongside ``household`` / ``lifestyle`` / ``preferences`` /
``goals``. List-valued top-level fields
(``dietary_needs``, ``allergies_and_intolerances``) replace wholesale.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ...models import ClientProfile, ProfileUpdateRequest


def _shallow_merge(existing: Any, sub: Any) -> Any:
    """Dict-wise shallow merge preserving the existing value's unset keys.

    When either side is not a dict we overwrite. The
    ``ProfileUpdateRequest`` schema guarantees dicts for the nested
    sub-objects, so this only matters on malformed input.
    """
    if isinstance(existing, dict) and isinstance(sub, dict):
        return {**existing, **sub}
    return sub


def merge_profile_structural(
    client_id: str,
    current: Optional[ClientProfile],
    update: Optional[ProfileUpdateRequest],
) -> ClientProfile:
    """Apply ``update`` onto ``current`` without any LLM call.

    Exercised by the intake agent's fallback path (LLM unavailable or
    its JSON malformed) and directly by tests. Always returns a valid
    ``ClientProfile`` with the given ``client_id``.
    """
    data: Dict[str, Any] = (
        current.model_dump() if current else ClientProfile(client_id=client_id).model_dump()
    )
    if not update:
        data["client_id"] = client_id
        return ClientProfile.model_validate(data)
    patch = update.model_dump(exclude_none=True)
    for key in ("dietary_needs", "allergies_and_intolerances"):
        if key in patch:
            data[key] = patch[key]
    for key in ("household", "lifestyle", "preferences", "goals", "biometrics", "clinical"):
        if key not in patch:
            continue
        sub = patch[key]
        if sub is None:
            continue
        data[key] = _shallow_merge(data.get(key) or {}, sub)
    data["client_id"] = client_id
    return ClientProfile.model_validate(data)
