"""Planning-level exceptions with no dependency on Temporal or any other runtime.

Kept separate from ``planning_team.temporal.answer_signal`` so core Planning code
(``planning_team.orchestrator``) never needs to import from the ``temporal``
subpackage to catch a control-flow signal its own ``answer_callback`` contract can
raise — Planning does not need to know it is running under Temporal (see
``system_design/planning_hitl_temporal_contract.md``).
"""

from __future__ import annotations

from typing import Any, Dict, List


class PlanningAnswerPauseSignal(Exception):
    """Internal control-flow signal: no answer is available yet for a Planning
    clarification question batch.

    Raised by a callback built via
    ``planning_team.temporal.answer_signal.build_temporal_planning_answer_callback``
    when constructed with ``submitted_answers=None``. Carries the exact
    discriminated-result payload a Temporal activity wrapper needs to return to its
    calling workflow instead of blocking (mirroring
    ``software_engineering_team.pause_cycle._ActivityPauseSignal``).

    Invariants:
        - Never crosses a workflow boundary — only ever raised inside plain
          Python / activity code, caught there and translated into a
          discriminated return value (e.g. ``{"outcome": "paused", ...}``),
          never propagated into ``@workflow.defn`` code.
    """

    def __init__(self, resume_token: str, pending_questions: List[Dict[str, Any]]) -> None:
        assert isinstance(resume_token, str) and resume_token, (
            "PlanningAnswerPauseSignal requires a non-empty resume_token"
        )
        self.resume_token = resume_token
        self.pending_questions = pending_questions
        super().__init__(f"paused: resume_token={resume_token}")


class PlanningDefaultsNotRecorded(Exception):
    """The terminal round fabricated answers but could not record that it did.

    Raised by a caller's ``on_defaulted`` hook (see
    ``software_engineering_team.temporal.activities._record_defaulted_questions``)
    when the durable write of the audit record fails. It exists as its own type
    for one reason: to survive the two boundaries that would otherwise convert it
    into a warning.

    ``poll_until_terminal`` folds any ``on_poll`` exception that is not in its
    ``passthrough_exceptions`` into a failed status, and
    ``DocumentProductionAgent.run`` logs a failed PRA status and carries on
    producing a plan. A plain ``RuntimeError`` from the hook therefore does NOT
    fail the round -- it yields a successful activity with neither a completed
    PRA nor the audit record, which is precisely the silent fabrication the hook
    exists to prevent. Both boundaries pass this type through instead
    (``adapters.product_analysis.wait_for_product_analysis_completion`` and
    ``orchestrator.run_workflow``), so it reaches the activity and fails it.

    Failing is the intended outcome: a Temporal retry is the right response to a
    transient job-store blip, and the terminal attempt clears
    ``defaulted_questions`` before it runs, so the retry starts from a clean
    record rather than inheriting a half-written one.

    Invariants:
        - Raised only when answers were actually fabricated AND the write of
          their record failed. It never signals "nothing to record".
    """

    def __init__(self, job_id: str, record_count: int, cause: BaseException) -> None:
        assert isinstance(job_id, str) and job_id, (
            "PlanningDefaultsNotRecorded requires a non-empty job_id"
        )
        self.job_id = job_id
        self.record_count = record_count
        super().__init__(
            f"failed to record {record_count} defaulted Planning answer(s) for job "
            f"{job_id}: {cause}"
        )
