"""The negative guarantee: ``wait_for_answers`` never resumes without a real answer.

Every other test of this mechanism asserts what it does when a signal arrives.
This file asserts what it does when one does NOT -- which is the defining
property, and the one a positive-path suite cannot reach. The failure mode it
guards is concrete rather than theoretical: Planning's ``resolve_pra_answers``
auto-picks the ``is_default`` option whenever no answer callback is supplied,
so a wait that quietly gave up and returned something would not raise an error
anywhere -- it would produce a plan built on an answer no human ever saw.

Proving "stays paused forever" cannot be done by waiting; a test that slept
would only prove "stays paused for a few seconds". So these run against a real
time-skipping ``WorkflowEnvironment`` and jump the server clock a decade
forward, which is the only way to distinguish an unbounded wait from a
generously-bounded one.

Three assertions carry the weight, and each covers a hole the others leave:

* the workflow is still ``RUNNING`` -- but so is a workflow stuck in a
  workflow-task retry loop, so history must also show no ``WorkflowTaskFailed``;
* history holds no terminal event -- but that is also true of a run that never
  started, so ``parked_state`` must show the pause armed on the token with no
  answer latched;
* ``handle.result()`` does not resolve -- and this one has to run inside
  ``auto_time_skipping_disabled()``, or the client's own auto-skip races the
  clock forward and the timeout measures the SDK rather than the wait.

Marked ``integration`` like every other ``WorkflowEnvironment`` test in this
repo; CI runs them under ``-m integration`` in ``test-shared-packages`` with
``TEMPORAL_TEST_SERVER_REQUIRED`` set, so a failed test-server download fails
the job rather than skipping it. A negative guarantee asserted by a test that
silently stops running is not a guarantee.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from shared.hitl.temporal_signal import SUBMIT_ANSWERS_SIGNAL
from shared.hitl.tests._probe_env import ANSWERS, probe_worker, wait_until_parked
from shared.hitl.tests._wait_probe_workflow import WAIT_PROBE_TASK_QUEUE, HitlWaitProbeWorkflow

RESUME_TOKEN = "probe-job-1:abc123"

#: Long enough that any plausible bounded wait -- a forgotten
#: ``start_to_close_timeout``, a "generous" 30-day fallback, a run timeout
#: someone adds later -- would have fired well inside it. Skipped, not slept.
A_DECADE = timedelta(days=3650)

#: Payloads that must all be refused. Ordered roughly by how far each one gets
#: into the handler, so a regression that breaks one rejection branch fails
#: here rather than in a single opaque assertion.
MALFORMED_PAYLOADS = (
    "not-a-dict-at-all",
    None,
    42,
    {},
    {"resume_token": RESUME_TOKEN},
    {"resume_token": RESUME_TOKEN, "answers": []},
    {"resume_token": RESUME_TOKEN, "answers": "not-a-list"},
    {"resume_token": RESUME_TOKEN, "answers": [{"question_id": "q1", "typo_field": "x"}]},
    {"resume_token": RESUME_TOKEN, "answers": [{"selected_option_id": "yes"}]},
    {"resume_token": "some-other-token", "answers": ANSWERS},
    {"answers": ANSWERS},
)


async def _assert_still_parked(env, handle, *, expect_token: str = RESUME_TOKEN) -> None:
    """Assert the workflow is parked on ``expect_token`` holding no answer.

    Preconditions:
        - ``env`` is a live time-skipping ``WorkflowEnvironment``; ``handle``
          refers to a probe workflow that has already reached its wait.
    Postconditions:
        - Raises ``AssertionError`` unless ALL of: the server clock actually
          advanced by ``A_DECADE`` (so the test cannot pass vacuously on an
          environment where skipping silently no-ops), the execution status is
          ``RUNNING``, history carries no terminal event and no
          ``WorkflowTaskFailed``, ``parked_state`` reports the pause armed on
          ``expect_token`` with nothing latched, and ``handle.result()`` does
          not resolve within a real-time budget.
        - Leaves the workflow running; the caller decides whether to resume or
          terminate it.
    """
    from temporalio.api.enums.v1 import EventType
    from temporalio.client import WorkflowExecutionStatus

    events = list((await handle.fetch_history()).events)
    assert events, "the probe has no history yet; call wait_until_parked before asserting it is parked"
    # Checked BEFORE skipping, and phrased as its own assertion, because a
    # server-side execution or run timeout would end this workflow during the
    # skip and every assertion below would then report a resolved wait -- a
    # true statement about a workflow the environment killed, not about the
    # mechanism. Failing here instead names the real cause.
    started = events[0].workflow_execution_started_event_attributes
    assert not started.HasField("workflow_execution_timeout") and not started.HasField("workflow_run_timeout"), (
        "the probe was started with an execution or run timeout "
        f"(execution={started.workflow_execution_timeout}, run={started.workflow_run_timeout}); "
        f"skipping {A_DECADE.days} days would then end it on a deadline rather than proving the wait is unbounded"
    )

    before = await env.get_current_time()
    await env.sleep(A_DECADE)
    after = await env.get_current_time()
    assert after - before >= A_DECADE, (
        f"the environment did not actually skip time ({before} -> {after}); every assertion below "
        "would then be measuring a wait that was never given the chance to expire"
    )

    description = await handle.describe()
    assert description.status == WorkflowExecutionStatus.RUNNING, (
        f"the wait resolved on its own after {A_DECADE.days} skipped days (status={description.status}); "
        "an unanswered pause must never reach a terminal state"
    )

    event_types = {int(e.event_type) for e in (await handle.fetch_history()).events}
    terminal = {
        EventType.EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED,
        EventType.EVENT_TYPE_WORKFLOW_EXECUTION_FAILED,
        EventType.EVENT_TYPE_WORKFLOW_EXECUTION_TIMED_OUT,
        EventType.EVENT_TYPE_WORKFLOW_EXECUTION_CONTINUED_AS_NEW,
    }
    assert not event_types & {int(t) for t in terminal}, (
        f"history reached a terminal event without an answer; event_type ints={sorted(event_types)}"
    )
    # A workflow whose signal handler raised would also be non-terminal and
    # still RUNNING -- permanently stranded in a task-retry loop rather than
    # cleanly paused. The two are indistinguishable from status alone, and only
    # one of them is the guarantee.
    assert int(EventType.EVENT_TYPE_WORKFLOW_TASK_FAILED) not in event_types, (
        "a workflow task failed -- the workflow is stranded in a retry loop, not parked; "
        "the signal handler's never-raise contract has been broken"
    )

    state = await handle.query(HitlWaitProbeWorkflow.parked_state)
    assert state == {"active_resume_token": expect_token, "has_submitted_answers": False}, (
        f"the pause is not armed as expected: {state}"
    )

    # Auto time-skipping would fast-forward this wait instead of measuring it,
    # turning a real-time timeout into an assertion about the SDK's clock.
    with env.auto_time_skipping_disabled():
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(handle.result(), timeout=2)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_an_unanswered_wait_never_completes_even_after_a_decade_of_skipped_time() -> None:
    """The headline guarantee: send nothing at all, skip ten years, and the
    workflow is still parked on its token with no answer -- not completed, not
    timed out, not resumed with a fabricated batch."""
    from shared.temporal.testing import workflow_environment

    async with workflow_environment() as env:
        async with probe_worker(env):
            handle = await env.client.start_workflow(
                HitlWaitProbeWorkflow.run,
                RESUME_TOKEN,
                id="hitl-wait-probe-never-answered",
                task_queue=WAIT_PROBE_TASK_QUEUE,
            )
            await wait_until_parked(handle)

            await _assert_still_parked(env, handle)

            # Terminate explicitly: a workflow left parked would otherwise keep
            # the worker's task poller busy through environment shutdown.
            await handle.terminate(reason="test finished; the probe is meant to still be waiting")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_signal_delivered_while_parked_resumes_with_exactly_those_answers() -> None:
    """The positive counterpart, in its simplest form: park first, THEN signal.
    Distinct from the signal-before-wait test next door, which exercises the
    buffer-drain path instead -- this one proves the latch works while the
    workflow is genuinely suspended, which is the ordering production sees."""
    from temporalio.worker import Replayer

    from shared.temporal.testing import workflow_environment

    async with workflow_environment() as env:
        async with probe_worker(env):
            handle = await env.client.start_workflow(
                HitlWaitProbeWorkflow.run,
                RESUME_TOKEN,
                id="hitl-wait-probe-signal-while-parked",
                task_queue=WAIT_PROBE_TASK_QUEUE,
            )
            await wait_until_parked(handle)
            assert (await handle.query(HitlWaitProbeWorkflow.parked_state))["active_resume_token"] == RESUME_TOKEN

            await handle.signal(SUBMIT_ANSWERS_SIGNAL, {"resume_token": RESUME_TOKEN, "answers": ANSWERS})

            with env.auto_time_skipping_disabled():
                result = await asyncio.wait_for(handle.result(), timeout=30)
            history = await handle.fetch_history()

    assert result == ANSWERS
    await Replayer(workflows=[HitlWaitProbeWorkflow]).replay_workflow(history)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_malformed_payloads_leave_the_workflow_parked_then_a_valid_one_resumes_it() -> None:
    """Eleven bad payloads, then a good one. Two claims in one run, because
    neither is worth much alone: rejection that also broke the latch would be
    a worse bug than acceptance, so proving the workflow stays parked is only
    half of it -- it must still be *answerable* afterwards.

    This is also the only place the ``payload: Any = None`` annotation is
    tested against Temporal's real data converter. The unit suite asserts the
    signature introspectively; a non-dict payload only actually reaches the
    handler body here, and a ``Dict[str, Any]`` annotation would fail argument
    conversion before any validation ran -- stranding the workflow permanently,
    since Temporal replays that failure forever."""
    from temporalio.worker import Replayer

    from shared.temporal.testing import workflow_environment

    async with workflow_environment() as env:
        async with probe_worker(env):
            handle = await env.client.start_workflow(
                HitlWaitProbeWorkflow.run,
                RESUME_TOKEN,
                id="hitl-wait-probe-malformed-payloads",
                task_queue=WAIT_PROBE_TASK_QUEUE,
            )
            await wait_until_parked(handle)

            for payload in MALFORMED_PAYLOADS:
                await handle.signal(SUBMIT_ANSWERS_SIGNAL, payload)
            # A zero-argument delivery -- a forwarding shim that dropped an
            # empty payload, say. It binds payload=None through the handler's
            # default rather than raising TypeError before the body runs.
            await handle.signal(SUBMIT_ANSWERS_SIGNAL)

            await _assert_still_parked(env, handle)

            await handle.signal(SUBMIT_ANSWERS_SIGNAL, {"resume_token": RESUME_TOKEN, "answers": ANSWERS})
            with env.auto_time_skipping_disabled():
                result = await asyncio.wait_for(handle.result(), timeout=30)
            history = await handle.fetch_history()

    assert result == ANSWERS, "the rejected payloads corrupted the latch: a valid answer no longer resumes the wait"
    await Replayer(workflows=[HitlWaitProbeWorkflow]).replay_workflow(history)


def test_every_malformed_payload_is_actually_rejected_by_the_handler() -> None:
    """Not integration-marked: the fixture above is only meaningful if each of
    its payloads really is refused, and where the test server is unreachable
    nothing would check that. Drives the handler directly with a pause armed,
    so a payload that silently became VALID (a schema field added later, say)
    fails here instead of quietly weakening the integration test into one that
    resumes early and still passes."""
    for payload in MALFORMED_PAYLOADS:
        wf = HitlWaitProbeWorkflow()
        wf._active_resume_token = RESUME_TOKEN

        wf.submit_answers(payload)

        assert wf._submitted_answers is None, f"payload was accepted but the fixture calls it malformed: {payload!r}"
        assert wf._active_resume_token == RESUME_TOKEN, f"a rejected payload disarmed the pause: {payload!r}"
