"""Probe workflow for the durable-wait integration tests in
``test_temporal_signal_replay.py`` and ``test_temporal_signal_no_default.py``.

Kept in its own module rather than inside a test file so the temporalio
workflow sandbox re-imports a plain module instead of a pytest test module when
it loads the workflow class. The module name has no ``test_`` prefix, so pytest
does not collect it.

Preconditions:
    - ``backend/agents`` and ``backend`` are on ``sys.path`` (the ``shared_*``
      convention).
Postconditions:
    - Importing has no side effects beyond class/constant definition.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from shared.hitl.temporal_signal import HitlAnswerSignalMixin

#: Dedicated queue so a probe worker never picks up a real team's tasks.
WAIT_PROBE_TASK_QUEUE = "shared-hitl-wait-probe"

#: Name of the parked-state query, as a constant so a test asserting on the
#: query and the workflow declaring it cannot drift apart silently.
PARKED_STATE_QUERY = "parked_state"


@workflow.defn(name="HitlWaitProbeWorkflow")
class HitlWaitProbeWorkflow(HitlAnswerSignalMixin):
    """The smallest workflow that exercises ``wait_for_answers`` end to end.

    Invariants:
        - Composes ``HitlAnswerSignalMixin`` and nothing else, so a test failure
          here is attributable to the mixin rather than to surrounding workflow
          logic. It defines no ``__init__``, so the mixin's runs.
        - Schedules no activities: the only history this workflow produces is
          start, workflow tasks, the signal, and completion — which is exactly
          the history a replay-determinism check should be reading.
        - Sets no run or execution timeout, so a test that skips time forward
          is observing the wait itself rather than a deadline the SDK would
          have enforced regardless. A probe that could time out would make
          "still running after skipped time" unprovable.
    """

    @workflow.run
    async def run(self, resume_token: str) -> Optional[List[Dict[str, Any]]]:
        """Park on ``resume_token`` and return whatever answers resume the wait.

        Preconditions:
            - ``resume_token`` is a non-empty ``str`` (enforced downstream by
              ``wait_for_answers``).
        Postconditions:
            - Returns only after a validated, token-matching ``submit_answers``
              signal lands; returns that batch. Never completes otherwise —
              there is no timeout and no default.
        """
        return await self.wait_for_answers(resume_token)

    @workflow.query(name=PARKED_STATE_QUERY)
    def parked_state(self) -> Dict[str, Any]:
        """Report whether a pause is armed and whether an answer is latched.

        Exists so a test can distinguish "armed on this token, holding no
        answer" from the far weaker "has not completed yet". Without it, a
        no-default assertion can only observe the absence of a completion
        event, which a crashed, stuck, or never-started workflow would satisfy
        just as well.

        Preconditions:
            - None. Temporal serves a query at any point in the run, including
              while ``run`` is suspended inside ``wait_for_answers``.
        Postconditions:
            - Returns the armed ``resume_token`` (``None`` when no pause is
              armed) and whether a validated batch is latched and unconsumed.
              Deliberately does NOT return the answers themselves: a query that
              handed back answer content could be mistaken for -- or quietly
              grow into -- a second way out of the pause, and this workflow
              exists to prove there is exactly one.
            - Mutates no workflow state, so it is replay-safe and cannot
              perturb the wait it is observing. Queries produce no history
              events, so calling it does not alter what a later replay sees.
        """
        return {
            "active_resume_token": self._active_resume_token,
            "has_submitted_answers": self._submitted_answers is not None,
        }
