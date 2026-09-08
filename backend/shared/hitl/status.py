"""Materialization of stored HITL records into typed models.

Used by the job-status routes to turn raw lists stored on a job record —
``pending_questions`` and ``defaulted_questions`` — into typed instances for the
response. Both helpers degrade rather than raise: a status endpoint that 500s on
a corrupt record tells the user nothing.
"""

from __future__ import annotations

from typing import Any, List, Optional

from shared.hitl.models import DefaultedQuestion, PendingQuestion


def pending_questions_from_raw(raw: List[Any]) -> List[PendingQuestion]:
    """Build :class:`PendingQuestion` models from a stored ``pending_questions`` list.

    Preconditions:
        - ``raw`` is the stored ``pending_questions`` value (an iterable; entries
          are expected to be dicts but may be malformed).
    Postconditions:
        - Returns one :class:`PendingQuestion` per dict entry, built with
          ``model_validate`` so **every** field the record carries is preserved
          (including ``recommendation``/``allow_multiple`` and nested option
          ``rationale``/``confidence``) — a full-fidelity round-trip, not a
          hand-enumerated subset.
        - Non-dict entries are skipped, so a corrupted record cannot raise.
        - Raises ``pydantic.ValidationError`` if a dict entry is missing a
          required field (``id``/``question_text``) or has a mistyped one — the
          same failure the equivalent direct construction would raise.
    """
    return [PendingQuestion.model_validate(q) for q in raw if isinstance(q, dict)]


def defaulted_questions_from_raw(raw: Any) -> List[DefaultedQuestion]:
    """Build :class:`DefaultedQuestion` models from a stored ``defaulted_questions`` list.

    The sibling of :func:`pending_questions_from_raw`, and deliberately its
    neighbour: this is a cross-team record — written by Planning's terminal-round
    answer callback, read by the SE status API — so its materialization belongs
    with the rest of the HITL contract rather than in either team's local code,
    where the two copies would be free to drift apart silently.

    Preconditions:
        - None. ``raw`` is whatever the job store holds under the key, which may
          be absent, a non-list, or a list of malformed entries.
    Postconditions:
        - Returns one :class:`DefaultedQuestion` per dict entry. A non-list, and
          non-dict entries inside a list, are dropped rather than raising.
        - Each field is coerced, never trusted: a missing or null ``question_id``
          becomes ``""`` (the model forbids null there), and the three descriptive
          fields pass ``None`` through as ``None`` while stringifying anything
          else. A corrupt record therefore renders as text rather than failing
          validation on fields whose whole purpose is to be readable.
        - An empty result is meaningful and not merely an absence: it is the claim
          that every answer behind this plan came from a person. That is why a
          malformed value degrades to empty — it matches what a job that defaulted
          nothing reports, which is overwhelmingly the common case.
        - Non-dict entries are dropped while valid dicts in the same list survive.
          Discarding a real record alongside the junk would UNDER-report fabricated
          answers, which is the failure direction this field exists to close.
    """
    if not isinstance(raw, list):
        return []
    return [
        DefaultedQuestion(
            question_id=str(entry.get("question_id") or ""),
            question_text=_optional_str(entry.get("question_text")),
            selected_option_id=_optional_str(entry.get("selected_option_id")),
            selected_option_label=_optional_str(entry.get("selected_option_label")),
        )
        for entry in raw
        if isinstance(entry, dict)
    ]


def _optional_str(value: Any) -> Optional[str]:
    """Coerce a stored value to a str, or None.

    Postconditions: ``None`` stays ``None``; anything else is stringified rather
    than rejected, so a corrupt record renders as text instead of failing
    validation on a field whose whole purpose is to be readable.
    """
    return None if value is None else str(value)
