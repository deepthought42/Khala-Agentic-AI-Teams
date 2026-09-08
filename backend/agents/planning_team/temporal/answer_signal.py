"""Temporal-durable answer-callback primitive for Planning clarification questions.

Provides the signal + ``wait_condition`` mechanism a Temporal workflow needs to
pause durably (surviving worker restarts) until a human answers a Planning
clarification question, plus an adapter that presents Planning's existing
``answer_callback: Callable[[list], list]`` contract (the same shape
``software_engineering_team.orchestrator._build_planning_answer_callback``
already satisfies for thread mode) without Planning's own code needing to
know it is running under Temporal.

Modeled directly on the coding team's ``submit_answers`` signal
(``software_engineering_team/temporal/coding_team_workflow.py``) and its
``_ActivityPauseSignal`` activity-side pause exception
(``software_engineering_team/pause_cycle.py``). Full contract/rationale in
``system_design/planning_hitl_temporal_contract.md``.

This module deliberately stops short of wiring into a concrete workflow or
activity (``planning_team/temporal/activities.py``) — that is separate,
follow-on work. ``PlanningAnswerSignalMixin`` is a plain mixin any
``@workflow.defn`` class can inherit; nothing here assumes which workflow
class will use it.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Callable, Dict, List, Optional

from temporalio import workflow

from planning_team.exceptions import PlanningAnswerPauseSignal

__all__ = [
    "SUBMIT_PLANNING_ANSWERS_SIGNAL",
    "PlanningAnswerPauseSignal",
    "build_temporal_planning_answer_callback",
    "PlanningAnswerSignalMixin",
]

logger = logging.getLogger(__name__)

# Wire shape fixed by system_design/planning_hitl_temporal_contract.md.
SUBMIT_PLANNING_ANSWERS_SIGNAL = "submit_planning_answers"

# PlanningAnswerPauseSignal itself now lives in planning_team.exceptions (no Temporal
# dependency), so planning_team.orchestrator can catch it without importing this
# subpackage. Re-exported here (imported above) since this module raises it and is
# where existing callers already look for it.


def _option_confidence(option: Dict[str, Any]) -> float:
    """``option``'s confidence as a float, 0.0 when absent or unusable.

    Postconditions: never raises; a ``confidence`` that is missing, non-numeric,
        bool, non-finite, or too large to convert to a float scores 0.0, so a
        malformed option can never outrank a well-formed one. Three exclusions
        are not obvious:

        - ``bool`` is an ``int`` subclass, so ``True`` would otherwise score
          1.0 -- ahead of every real option.
        - ``NaN`` passes the numeric check but loses every ``>`` comparison, so
          ``max`` KEEPS a leading NaN option over later, higher-confidence
          ones. That is a malformed option outranking well-formed ones, which
          is exactly what this postcondition rules out. ``json.loads`` accepts
          a bare ``NaN`` token, and these dicts originate from LLM-parsed
          output, so it is reachable rather than theoretical.
        - An ``int`` beyond float range raises ``OverflowError`` from
          ``float()`` rather than producing a value; ``json.loads`` parses
          integer tokens into unbounded ints, so the same source can supply
          one. It is caught, not allowed to escape.
    """
    value = option.get("confidence")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    try:
        confidence = float(value)
    except OverflowError:
        # An int beyond ~1e308. ``json.loads`` parses integer tokens into
        # unbounded Python ints, so this is reachable from the same LLM-parsed
        # output the exclusions below guard against -- and letting it raise
        # would crash the resumed activity on the final round instead of
        # defaulting, which is the one thing this path must not do.
        return 0.0
    return confidence if math.isfinite(confidence) else 0.0


def _default_answer(question: Dict[str, Any]) -> Dict[str, Any]:
    """Build a submittable answer for a question nobody answered.

    The selection policy is deliberately identical to
    ``product_requirements_analysis_agent.user_communication.get_default_option``,
    which thread mode's auto-answer path uses: the ``is_default`` option, else the
    highest-confidence one, else ``None``. Only the input shape differs -- that
    function takes an ``OpenQuestion``, this one the wire dicts
    ``convert_to_pending_questions`` emits, which carry ``confidence`` on every
    option. Diverging here (e.g. falling back to list order) would mean the SAME
    question gets a different defaulted answer depending on which runtime mode
    spent its pause budget.

    Preconditions:
        - ``question`` is a dict whose ``"id"`` is a str (the caller filters).
    Postconditions:
        - Returns an ``{"question_id", "selected_option_id", "other_text"}`` dict
          shaped for ``shared.hitl.models.AnswerSubmission``.
        - The option chosen is the first flagged ``is_default``; failing that the
          highest-confidence well-formed option (ties broken by list order, since
          ``max`` returns the first maximal element -- matching
          ``get_default_option``'s stable sort); failing that ``None``.
          ``selected_option_id`` is Optional on that model, and a question with no
          options carries a free-text placeholder anyway.
        - Malformed options (non-dict, or a non-str ``id``) are skipped rather
          than raising, so a garbled batch still yields a submittable answer.
    """
    options = question.get("options")
    chosen: Optional[Dict[str, Any]] = None
    if isinstance(options, list):
        well_formed = [
            opt for opt in options if isinstance(opt, dict) and isinstance(opt.get("id"), str)
        ]
        chosen = next((opt for opt in well_formed if opt.get("is_default")), None)
        if chosen is None and well_formed:
            chosen = max(well_formed, key=_option_confidence)
    return {
        "question_id": question["id"],
        "selected_option_id": chosen["id"] if chosen else None,
        "other_text": None,
    }


def _defaulted_record(question: Dict[str, Any], answer: Dict[str, Any]) -> Dict[str, Any]:
    """Pair a defaulted answer with enough of its question to be auditable.

    A bare ``question_id`` is not an audit record. ``plan_project_activity``
    clears ``pending_questions`` before the replay, and a defaulted terminal batch
    never raises a pause, so nothing else persists the questions these ids refer
    to -- and the ids are LLM-minted, so they are not stable across runs either. A
    reader handed only ids would see identifiers for decisions no human made, with
    no way to learn what was decided.

    Preconditions:
        - ``question`` is a well-formed pending-question dict (``id`` is a str;
          the caller filters).
        - ``answer`` is the matching output of :func:`_default_answer`.
    Postconditions:
        - Returns ``{"question_id", "question_text", "selected_option_id",
          "selected_option_label"}``. Never raises: a question with no text, or a
          chosen option carrying no label, yields ``None`` for that field rather
          than failing a resumed activity over presentation detail.
        - ``question_text`` accepts either the ``question_text`` or ``text``
          spelling, matching what ``_structure_planning_questions`` emits and what
          Planning's own question dicts carry.
        - This shape is for the audit record ONLY. It is deliberately not what the
          callback returns: PRA's answers route validates ``AnswerSubmission``, so
          the returned batch must stay ``{question_id, selected_option_id,
          other_text}`` or be rejected outright.
    """
    text = question.get("question_text") or question.get("text")
    selected_id = answer.get("selected_option_id")
    label: Optional[str] = None
    if selected_id is not None:
        options = question.get("options")
        if isinstance(options, list):
            for opt in options:
                if isinstance(opt, dict) and opt.get("id") == selected_id:
                    raw_label = opt.get("label")
                    label = raw_label if isinstance(raw_label, str) else None
                    break
    return {
        "question_id": answer["question_id"],
        "question_text": text if isinstance(text, str) else None,
        "selected_option_id": selected_id,
        "selected_option_label": label,
    }


def build_temporal_planning_answer_callback(
    resume_token: str,
    submitted_answers: Optional[List[Dict[str, Any]]] = None,
    next_resume_token: Optional[Callable[[], str]] = None,
    allow_repause: bool = True,
    on_defaulted: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
) -> Callable[[list], list]:
    """Build a ``Callable[[list], list]`` satisfying Planning's ``answer_callback``
    contract (``planning_team.orchestrator.resolve_pra_answers``), backed by the
    durable signal-wait mechanism instead of thread-mode's blocking poll loop.

    The shape of the result is dictated by what the consumer can actually act on.
    Planning's PRA path feeds it to ``adapters.product_analysis``, which POSTs it to
    the product-analysis answers route -- and that route rejects (400) any batch
    missing an answer for a question marked ``required``, which
    ``user_communication.convert_to_pending_questions`` stamps on every question it
    emits. So a partial answer set is not a weaker success than a full one: it is
    indistinguishable from silence, leaving the sub-job waiting until it times out.
    This callback therefore returns a COMPLETE set or does not return at all.

    Preconditions:
        - ``resume_token`` is a non-empty str uniquely identifying this pause
          round (the same token a workflow will arm via
          ``PlanningAnswerSignalMixin.wait_for_planning_answers``).
        - ``submitted_answers``, when not ``None``, is the exact list already
          resolved for this ``resume_token`` (e.g. via a validated
          ``submit_planning_answers`` signal) -- dicts shaped
          ``{"question_id": ..., "selected_option_id": ...}``, matching what
          thread-mode's ``_build_planning_answer_callback`` already returns.
        - ``next_resume_token``, when given, mints a FRESH token per call (see
          ``pause_cycle.mint_resume_token``: a token is unique per pause round
          and never reused), for the case below where a resumed run has to
          pause again. Omitted, a re-pause reuses ``resume_token``, which is
          still preferable to answering a batch silently but leaves the two
          rounds sharing one token.
        - ``on_defaulted``, when given, is a one-argument callable accepting the
          audit records for the questions this callback FABRICATED answers to on
          a terminal round (never the human's own answers, and never the combined
          list) -- ``_defaulted_record``-shaped, carrying the question text and
          the chosen option's label, not just ids. It is the caller's hook for
          recording that fact somewhere durable: a ``logger.warning`` inside an
          activity worker is not a record anything downstream can read, and a
          defaulted plan that looks fully human-answered in the job record is the
          silent auto-answer this callback exists to prevent, merely relocated.

          **It can be called more than once for the same callback object.**
          ``wait_for_product_analysis_completion``'s ``_on_poll`` invokes the
          callback on every poll while PRA reports ``waiting_for_answers``, and
          PRA's own review loop raises several unrelated clarification rounds
          with fresh ids; with ``allow_repause=False`` nothing raises, so each
          round is defaulted in turn. A caller that OVERWRITES its store on each
          call therefore keeps only the last round -- it must accumulate, keyed on
          question identity (``question_id`` AND ``question_text`` together, never
          the id alone: PRA's parser falls back to a positional ``q{index}`` id,
          so two unrelated rounds can reuse one).

          It must not swallow its own failures; see the postcondition below.
        - ``allow_repause`` is a bool. ``False`` forbids a further pause: when
          ``submitted_answers`` is provided, the callback resolves whatever it is
          handed, defaulting any unmatched question. It does NOT make the
          no-answers callback resolve -- with ``submitted_answers=None`` there is
          nothing to resolve with, so that callback still raises the initial pause
          on ``resume_token`` regardless of this flag (see the postcondition
          below). A caller that loops on
          pauses MUST bound that loop and pass ``False`` on its final round,
          because nothing here guarantees convergence on its own: a resume replays
          Planning from scratch, and an ``OpenQuestion.id`` reaches the model
          straight from LLM output
          (``product_requirements_analysis_agent.question_processing.parse_open_question``),
          so a re-run can mint fresh ids for questions the user has already
          answered and each round would then pause on the next batch forever.
    Postconditions:
        - Returns a callable ``cb(questions) -> list``.
        - When ``submitted_answers`` is ``None``: calling ``cb`` never returns --
          it raises ``PlanningAnswerPauseSignal(resume_token, questions)``,
          carrying the exact ``questions`` passed in verbatim as
          ``pending_questions`` for a caller to persist/relay.
        - When ``submitted_answers`` is provided and every well-formed question in
          the batch has a matching submitted answer, ``cb`` returns those matches
          in ``submitted_answers``' order and nothing else. It never fabricates an
          answer for a question the submitter did answer, and never overrides one
          with a default.
        - When any well-formed question has no matching answer and ``allow_repause``
          is true, ``cb`` raises ``PlanningAnswerPauseSignal`` rather than submitting
          a set the route would reject -- on a freshly minted token when
          ``next_resume_token`` was given, else on the original ``resume_token``
          (see that parameter's precondition). That covers
          both "the submitter skipped this one" and "the replay opened a question
          nobody has seen"; either way the answer that would let Planning proceed
          does not exist yet, and inventing one is the silent auto-answer both
          runtime modes exist to prevent.
        - When any well-formed question has no matching answer and ``allow_repause``
          is false, ``cb`` returns the matches plus a defaulted answer per unmatched
          question (see :func:`_default_answer`), logs a warning naming them, and --
          when ``on_defaulted`` was given -- calls it once for THIS batch with the
          audit records for just those fabricated answers, in ``missing`` order,
          before returning. Once per batch is not once per callback: see the
          precondition above. An exception
          raised by ``on_defaulted`` PROPAGATES: it is not caught, and the callback
          returns nothing. Swallowing it would produce the one outcome this whole
          mechanism rules out -- a plan built on fabricated answers with no surviving
          record that they were fabricated. Failing the round is recoverable; an
          unrecorded default is not.
        - ``on_defaulted`` is never called on any other path: not on the initial
          pause callback, not on a round that resolves fully, and not on one that
          re-pauses. Nothing was fabricated on those paths, and a caller must be
          able to treat a call as proof that it was.
          The pause budget is spent, so the choice is between a defaulted answer and
          a sub-job that waits until it times out; a default that is announced beats
          a hang. The option it picks follows the same policy
          ``user_communication.get_default_option`` applies on the thread-mode
          auto-answer path -- is_default, else highest confidence -- so the two
          runtime modes default a given question identically.
        - A malformed question entry (non-dict, or an ``id`` that is not a str)
          carries nothing a submitter could ever answer and nothing the route would
          accept, so it neither matches, blocks, nor gets a default -- it is skipped
          entirely. Likewise a non-dict entry in ``submitted_answers`` (a malformed
          signal's ``answers`` list is validated as a list, not a list-of-dicts) is
          skipped rather than raising ``AttributeError`` out of a resumed activity,
          and matching requires ``question_id`` to be a ``str`` so an unhashable one
          never crashes the set-membership test.
        - At most ONE answer is returned per question. That list is validated as a
          list, so it can carry the same ``question_id`` twice, and nothing
          downstream catches it: the product-analysis route compares sets of ids,
          so a duplicate satisfies both its required-coverage and unknown-id
          checks and is then stored verbatim. The first entry per id wins, in
          ``submitted_answers`` order.
    Invariants:
        - The callback never fabricates an answer while another pause round
          remains. It defaults only on a round the caller has explicitly declared
          terminal via ``allow_repause=False``, and every such default is reported
          to ``on_defaulted`` when one was supplied.
    """
    assert isinstance(resume_token, str) and resume_token, (
        "build_temporal_planning_answer_callback requires a non-empty resume_token"
    )
    assert isinstance(allow_repause, bool), (
        "build_temporal_planning_answer_callback requires a bool allow_repause"
    )
    # Checked here, not at the re-pause site: a non-callable (a token string
    # mistaken for ``resume_token``) would otherwise stay silent until a batch
    # actually re-pauses, and surface as ``TypeError: 'str' object is not
    # callable`` from inside a resumed activity -- the one place a clear message
    # is hardest to come by.
    assert next_resume_token is None or callable(next_resume_token), (
        "build_temporal_planning_answer_callback requires next_resume_token to be a "
        "zero-argument callable that mints a FRESH token (e.g. pause_cycle."
        "mint_resume_token), or None"
    )
    assert on_defaulted is None or callable(on_defaulted), (
        "build_temporal_planning_answer_callback requires on_defaulted to be a "
        "one-argument callable receiving the fabricated answers, or None"
    )

    if submitted_answers is None:

        def _pause_cb(questions: list) -> list:
            raise PlanningAnswerPauseSignal(resume_token, list(questions))

        return _pause_cb

    resolved = list(submitted_answers)

    def _resolved_cb(questions: list) -> list:
        askable = [q for q in questions if isinstance(q, dict) and isinstance(q.get("id"), str)]
        question_ids = {q["id"] for q in askable}
        # First-wins dedup, not a plain filter: a signal's ``answers`` is
        # validated as a list, not a list of distinct answers, so two entries
        # can carry the same question_id. Nothing downstream rejects that --
        # the product-analysis route compares SETS of ids, so duplicates pass
        # its required/unknown checks and are stored verbatim -- which leaves
        # which answer actually applies decided by iteration order.
        matched_by_id: Dict[str, Dict[str, Any]] = {}
        for a in resolved:
            if (
                isinstance(a, dict)
                and isinstance(a.get("question_id"), str)
                and a["question_id"] in question_ids
                and a["question_id"] not in matched_by_id
            ):
                matched_by_id[a["question_id"]] = a
        matched = list(matched_by_id.values())
        answered_ids = set(matched_by_id)
        missing = [q for q in askable if q["id"] not in answered_ids]
        if not missing:
            return matched
        if allow_repause:
            raise PlanningAnswerPauseSignal(
                next_resume_token() if next_resume_token is not None else resume_token,
                list(questions),
            )
        logger.warning(
            "Planning pause budget exhausted; defaulting %d unanswered question(s) so the "
            "product-analysis sub-job can resume instead of waiting out its poll timeout "
            "(ids: %s). Planning question ids are LLM-minted and can differ across a replay, "
            "so a further pause is not guaranteed to converge.",
            len(missing),
            ", ".join(q["id"] for q in missing),
        )
        defaulted = [_default_answer(q) for q in missing]
        if on_defaulted is not None:
            records = [_defaulted_record(q, a) for q, a in zip(missing, defaulted)]
            # Deliberately unguarded. A hook that fails silently leaves a plan
            # built on fabricated answers with nothing anywhere saying so --
            # exactly the failure the hook exists to close.
            on_defaulted(records)
        return matched + defaulted

    return _resolved_cb


class PlanningAnswerSignalMixin:
    """Mixin giving a Temporal workflow class durable pause/resume capability for
    Planning clarification questions, via the ``submit_planning_answers`` signal.

    Invariants:
        - ``self._active_resume_token`` is non-None only while this workflow is
          waiting on a pause it has armed (between
          ``wait_for_planning_answers`` being called for a token and that same
          call returning) — so ``submit_planning_answers`` can tell a fresh
          submission for the CURRENT pause apart from a stale one for an
          already-resolved pause.
        - ``self._submitted_answers`` is non-None only in the narrow window
          between a validated ``submit_planning_answers`` signal being
          delivered and ``wait_for_planning_answers`` consuming it (which
          resets it to ``None`` before returning) — so a stale answer batch
          from one pause round can never be mistaken for a fresh one in the
          next.
        - ``self._buffered_signals`` holds at most one early-arrived answer
          batch per not-yet-armed ``resume_token``. The moment
          ``wait_for_planning_answers`` arms a token it applies the matching
          buffered entry (if any) and clears the entire dict, so stale keys
          cannot accumulate across pause rounds in durable workflow state.
    """

    def __init__(self) -> None:
        super().__init__()
        self._active_resume_token: Optional[str] = None
        self._submitted_answers: Optional[List[Dict[str, Any]]] = None
        self._buffered_signals: Dict[str, List[Dict[str, Any]]] = {}

    @workflow.signal(name=SUBMIT_PLANNING_ANSWERS_SIGNAL)
    def submit_planning_answers(self, payload: Any) -> None:
        """Deliver a human answer batch for the current (or next) pause.

        Preconditions:
            - None enforced — ``payload`` arrives from outside the workflow, so
              this handler validates its shape defensively rather than trusting
              a precondition an external, unvalidated signal cannot guarantee.
              A well-formed payload is a dict shaped
              ``{"resume_token": str, "answers": list}``, per
              ``system_design/planning_hitl_temporal_contract.md``. The
              parameter is typed ``Any``, not ``Dict[str, Any]``, deliberately:
              Temporal's data converter type-checks a signal argument against
              its annotation *before* the handler body runs, so a ``Dict``
              annotation would raise ``TypeError`` for a non-dict payload
              during argument conversion — never reaching the ``isinstance``
              guard below — and an unhandled exception here fails the
              workflow task and, since Temporal replays history, would fail
              identically on every future replay, permanently stranding the
              workflow.
        Postconditions:
            - Any payload that is not a dict, or a dict without a list
              ``"answers"`` value, is ignored (returns without side effects).
            - When no pause is currently active
              (``self._active_resume_token is None``), a well-formed payload is
              treated as an early arrival for a pause not yet armed: a
              non-empty string ``resume_token`` is buffered in
              ``self._buffered_signals``, keyed by that token (first
              submission per token wins — an already-buffered token is left
              alone). A payload with no usable ``resume_token`` while no pause
              is active has nothing to key a buffer entry on and is dropped.
            - Otherwise, validates ``payload.get("resume_token")`` against
              ``self._active_resume_token``: a mismatch is ignored, not
              applied; once a batch is accepted for the current token, a
              second matching-token signal (a double-submit, or two clients
              racing) is ignored too — first submission per token wins. Only a
              token-matching first submission with a list ``"answers"`` sets
              ``self._submitted_answers`` to that list, satisfying a
              ``wait_condition`` predicate of
              ``self._submitted_answers is not None``.
        """
        if not isinstance(payload, dict):
            return
        answers = payload.get("answers")
        if not isinstance(answers, list):
            return
        resume_token = payload.get("resume_token")
        if self._active_resume_token is None:
            if isinstance(resume_token, str) and resume_token:
                self._buffered_signals.setdefault(resume_token, answers)
            return
        if resume_token != self._active_resume_token:
            return
        if self._submitted_answers is not None:
            return
        self._submitted_answers = answers

    async def wait_for_planning_answers(self, resume_token: str) -> List[Dict[str, Any]]:
        """Durably suspend this workflow until a matching ``submit_planning_answers``
        signal is delivered, then return the answers.

        Preconditions:
            - ``resume_token`` is a non-empty str identifying the pause round
              (must match what a caller persisted/relayed alongside a
              ``PlanningAnswerPauseSignal``'s ``resume_token``).
            - Only called from within ``@workflow.defn`` code (uses
              ``workflow.wait_condition``, which is only valid there).
        Postconditions:
            - Applies any signal already buffered for ``resume_token`` (a
              signal that arrived before this call armed the wait) and clears
              ``self._buffered_signals`` entirely — no stale buffered entry for
              a different token can leak into a later pause round.
            - Suspends (durably — this ``await`` survives a worker restart)
              until ``self._submitted_answers is not None``, i.e. until a
              validated, token-matching ``submit_planning_answers`` signal
              lands. There is no timeout and no default path: this method
              never returns without a real signal.
            - Returns the delivered answers list and resets
              ``self._active_resume_token``/``self._submitted_answers`` to
              ``None`` before returning, so a later pause round starts clean.
        """
        assert isinstance(resume_token, str) and resume_token, (
            "wait_for_planning_answers requires a non-empty resume_token"
        )
        self._active_resume_token = resume_token
        self._submitted_answers = self._buffered_signals.pop(resume_token, None)
        self._buffered_signals.clear()
        await workflow.wait_condition(lambda: self._submitted_answers is not None)
        answers = self._submitted_answers
        self._submitted_answers = None
        self._active_resume_token = None
        assert answers is not None
        return answers
