"""Shared human-in-the-loop (HITL) request/response schemas.

The "pending question / answer" contract used when a team pauses a job to ask
the user a product/design decision, plus the shared gate-review model
(:class:`HumanReview`) for approve/reject decisions with optional feedback.
Historically each team (coding_team, software_engineering_team) defined its own
near-identical copy; these are the reconciled **superset** models — every field
either team carried is present, and the fields unique to one team
(``recommendation``/``allow_multiple`` on :class:`PendingQuestion`,
``rationale``/``confidence`` on :class:`QuestionOption`) are optional-with-default
so they are safe for the team that never set them.

Pure data schemas; no runtime logic, no I/O.

Preconditions:
    - ``backend/agents`` is on ``sys.path`` (the ``shared_*`` convention).
Postconditions:
    - Import-side-effect free beyond class definition; importing never raises.

Invariants:
    - Additive fields are ``Optional`` (or have a default), so constructing a
      model from a dict that omits them, or serializing one to JSON, is safe for
      any caller and for the loose (non-validating) Angular frontend.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class QuestionOption(BaseModel):
    """A selectable option for a pending question."""

    id: str = Field(..., description="Unique identifier for this option.")
    label: str = Field(..., description="Display text for this option.")
    is_default: bool = Field(default=False, description="Whether this option is the suggested default.")
    rationale: Optional[str] = Field(None, description="Why this option is suggested.")
    confidence: Optional[float] = Field(None, description="Agent confidence in this option (0-1).")


class PendingQuestion(BaseModel):
    """A product/design decision a team escalated to the user before it could proceed."""

    id: str = Field(..., description="Unique identifier for this question.")
    question_text: str = Field(..., description="The question to display to the user.")
    context: Optional[str] = Field(None, description="Why this decision matters.")
    recommendation: Optional[str] = Field(
        None,
        description="Agent recommendation: which option to choose and why.",
    )
    options: List[QuestionOption] = Field(
        default_factory=list,
        description="Selectable answer options. The UI always offers an 'other' free-text option.",
    )
    required: bool = Field(default=True, description="Whether this question must be answered.")
    allow_multiple: bool = Field(
        default=False,
        description="True = checkboxes (select all that apply), False = radio buttons (select one).",
    )
    # Default is a fallback only: orchestrators always stamp ``source`` on stored
    # records, so the default is reached only for a record that omits the field.
    source: str = Field(
        default="planning",
        description="Origin of the question: planning, tech_lead, execution, engineer:<agent>, etc.",
    )


class AnswerSubmission(BaseModel):
    """A user's answer to a pending question."""

    question_id: str = Field(..., description="ID of the question being answered.")
    selected_option_id: Optional[str] = Field(
        None, description="ID of the selected option, or 'other' if custom text is provided."
    )
    other_text: Optional[str] = Field(None, description="Custom text when 'other' is selected.")


class DefaultedQuestion(BaseModel):
    """One clarification answer the system chose because nobody answered it.

    The cross-team audit record for a fabricated answer: produced by Planning's
    terminal-round answer callback and consumed by the SE status API and UI. It
    lives here, with the rest of the HITL contract, because the producer and the
    consumer sit in different teams — the exact shape this package exists to keep
    from being defined twice and drifting apart.

    Deliberately NOT the wire shape a callback returns to an answers route: that
    is ``AnswerSubmission`` (``question_id``/``selected_option_id``/``other_text``).
    This record carries the question's text and the chosen option's LABEL because
    the pause envelope holding the original questions is cleared before the plan
    ships, and the ids are LLM-minted — bare ids would name decisions no human
    made without saying what was decided.

    Invariants:
        - ``question_id`` is never null. A record with no usable id degrades to
          the empty string rather than raising: a status endpoint that 500s on a
          corrupt record tells the user nothing.
        - The three descriptive fields are nullable, and null is meaningful —
          the option fields when the question offered nothing to default to,
          ``question_text`` when the question carried none.
    """

    question_id: str = Field(
        default="",
        description="Id of the question that was defaulted; empty when the record carries none.",
    )
    question_text: Optional[str] = Field(
        default=None, description="The question as asked, or None when it carried no text."
    )
    selected_option_id: Optional[str] = Field(
        default=None, description="Id of the option chosen, or None when there was none to choose."
    )
    selected_option_label: Optional[str] = Field(
        default=None, description="Human-readable label of the chosen option, or None."
    )


class SubmitAnswersRequest(BaseModel):
    """Request body for submitting answers to a job's pending questions.

    ``resume_token`` is optional so this shared model stays backward-compatible for
    every caller that doesn't have a concept of one (thread-mode routes, SE's
    product-analysis answers route) — it is enforced (not via Pydantic, but an
    explicit check) only by a route in its native-Temporal-signal branch, per
    ``system_design/hitl_pause_resume_contract.md`` §3.
    """

    answers: List[AnswerSubmission] = Field(..., description="List of answers to submit.")
    resume_token: Optional[str] = Field(
        default=None,
        description="Echoes the resume_token from the pause notification/status poll this "
        "answer batch resolves. Required (and checked against the job record's persisted "
        "resume_token) only by a native-Temporal-signal-capable route; ignored elsewhere.",
    )


class HumanReview(BaseModel):
    """Human gate decision for a team run (approve / reject + optional feedback).

    Preconditions:
        - Callers must supply ``approved`` explicitly (no default).
    Postconditions:
        - Instance carries a boolean gate and a string ``feedback`` (empty if omitted).
    """

    approved: bool
    feedback: str = ""
