"""Tests for shared.hitl.status — full-fidelity materialization of stored HITL records."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.hitl.models import PendingQuestion
from shared.hitl.status import (
    defaulted_questions_from_raw,
    pending_questions_from_raw,
)


def test_empty_returns_empty():
    assert pending_questions_from_raw([]) == []


def test_preserves_superset_fields():
    raw = [
        {
            "id": "q1",
            "question_text": "Pick one?",
            "recommendation": "use strict",
            "allow_multiple": True,
            "required": True,
            "source": "tech_lead",
            "options": [
                {
                    "id": "strict",
                    "label": "Strict",
                    "is_default": True,
                    "rationale": "safer",
                    "confidence": 0.8,
                }
            ],
        }
    ]
    out = pending_questions_from_raw(raw)
    assert len(out) == 1
    q = out[0]
    assert isinstance(q, PendingQuestion)
    # The field-drop bug fixed by construction: recommendation/allow_multiple survive.
    assert q.recommendation == "use strict"
    assert q.allow_multiple is True
    assert q.source == "tech_lead"
    # Nested option superset fields survive too.
    assert q.options[0].rationale == "safer"
    assert q.options[0].confidence == 0.8


def test_skips_non_dict_entries():
    raw = [
        "not-a-dict",
        123,
        None,
        {"id": "q1", "question_text": "ok"},
    ]
    out = pending_questions_from_raw(raw)
    assert len(out) == 1
    assert out[0].id == "q1"


def test_missing_required_field_raises_validation_error():
    with pytest.raises(ValidationError):
        pending_questions_from_raw([{"question_text": "no id"}])


# --- defaulted_questions_from_raw -------------------------------------------------


def test_defaulted_empty_and_non_list_both_degrade_to_empty():
    """An empty result is a claim, not an absence: every answer came from a person.

    A non-list is a corrupt record, and degrading it to ``[]`` rather than raising is
    deliberate — a status endpoint that 500s tells a reader nothing, while ``[]`` is
    what the overwhelmingly common case (a job that defaulted nothing) reports.
    """
    assert defaulted_questions_from_raw([]) == []
    assert defaulted_questions_from_raw("not a list") == []
    assert defaulted_questions_from_raw(None) == []


def test_defaulted_round_trips_a_full_record():
    out = defaulted_questions_from_raw(
        [
            {
                "question_id": "q1",
                "question_text": "Which auth provider?",
                "selected_option_id": "okta",
                "selected_option_label": "Okta",
            }
        ]
    )
    assert len(out) == 1
    assert out[0].question_id == "q1"
    assert out[0].question_text == "Which auth provider?"
    assert out[0].selected_option_id == "okta"
    assert out[0].selected_option_label == "Okta"


def test_defaulted_drops_junk_entries_but_keeps_valid_ones_beside_them():
    """Dropping the whole list over one bad entry would UNDER-report fabrications.

    That is the failure direction this record exists to close, so a real record
    survives alongside the junk rather than being discarded with it.
    """
    out = defaulted_questions_from_raw(["junk", 42, None, {"question_id": "q1"}])
    assert [d.question_id for d in out] == ["q1"]


def test_defaulted_maps_a_null_question_id_to_empty_not_the_string_None():
    """``str(None)`` would surface the literal text "None" as a real question id.

    The three descriptive fields route through the null-aware coercion, so the id
    being the one field that degraded to misleading text was an inconsistency in an
    otherwise uniform path — and this is exactly the corrupt/future-shaped record the
    coercion exists to survive.
    """
    out = defaulted_questions_from_raw([{"question_id": None, "question_text": "T"}])
    assert out[0].question_id == ""
    assert out[0].question_text == "T"


def test_defaulted_passes_nulls_through_and_stringifies_everything_else():
    """Null is meaningful here: no option to default to, or a question with no text."""
    out = defaulted_questions_from_raw(
        [
            {
                "question_id": 7,
                "question_text": None,
                "selected_option_id": None,
                "selected_option_label": None,
            }
        ]
    )
    assert out[0].question_id == "7"
    assert out[0].question_text is None
    assert out[0].selected_option_id is None
    assert out[0].selected_option_label is None


def test_defaulted_tolerates_a_missing_label_beside_a_present_option_id():
    """The middle branch the UI renders: an id with no label is a real shape."""
    out = defaulted_questions_from_raw(
        [{"question_id": "q2", "selected_option_id": "redis", "selected_option_label": None}]
    )
    assert out[0].selected_option_id == "redis"
    assert out[0].selected_option_label is None
