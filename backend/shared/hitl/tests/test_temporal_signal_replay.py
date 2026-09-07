"""Replay-safety coverage for ``HitlAnswerSignalMixin.wait_for_answers``.

``test_temporal_signal.py`` proves the wait's SHAPE against a monkeypatched
``workflow.wait_condition``. This file proves the property that shape exists
for: the wait is durable, so a worker that dies while a workflow is parked can
be replaced by a fresh worker that rebuilds the pause purely from replayed
history and resumes correctly. The sibling
``test_temporal_signal_no_default.py`` proves the negative half -- that a wait
nobody answers never resumes at all.

The ``WorkflowEnvironment`` tests here are ``integration``-marked, so
``backend/conftest.py`` skips them unless pytest is invoked with
``-m integration`` -- the same status every other ``WorkflowEnvironment`` test
in this repo has. CI runs them under exactly that marker in the
``test-shared-packages`` job, with ``TEMPORAL_TEST_SERVER_REQUIRED`` set so a
failed test-server download fails the job instead of skipping (see
``shared.temporal.testing.workflow_environment``); locally, with that flag
unset, an unreachable ``temporal.download`` degrades to a skip. The structural
test at the bottom is NOT integration-marked: it runs in the ordinary suite and
pins that the probe workflow is a well-formed ``@workflow.defn`` composing the
mixin, so a broken probe surfaces even where the server is unreachable.

The worker/park scaffolding lives in ``_probe_env`` so this file and the
no-default sibling drive byte-identical workers -- a divergence there (a sticky
cache left enabled, say) would quietly weaken one file's proof.
"""

from __future__ import annotations

import asyncio

import pytest

from shared.hitl.temporal_signal import SUBMIT_ANSWERS_SIGNAL
from shared.hitl.tests._probe_env import ANSWERS, probe_worker, wait_until_parked
from shared.hitl.tests._wait_probe_workflow import WAIT_PROBE_TASK_QUEUE, HitlWaitProbeWorkflow

RESUME_TOKEN = "probe-job-1:abc123"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_wait_survives_a_worker_restart_and_replays_deterministically() -> None:
    """The acceptance criterion this story exists for: kill the worker while the
    workflow is parked, deliver the answer with NO worker running at all, then
    start a fresh worker. It must rebuild the pause from replayed history and
    resume with the real answers -- not restart, not default, not hang."""
    from temporalio.worker import Replayer

    from shared.temporal.testing import workflow_environment

    async with workflow_environment() as env:
        async with probe_worker(env):
            handle = await env.client.start_workflow(
                HitlWaitProbeWorkflow.run,
                RESUME_TOKEN,
                id="hitl-wait-probe-worker-restart",
                task_queue=WAIT_PROBE_TASK_QUEUE,
            )
            await wait_until_parked(handle)
        # Worker A is gone. The signal is durable server-side, so it is recorded
        # into history with nothing running to observe it -- the buffered/armed
        # distinction now has to survive purely as replayed state.
        await handle.signal(SUBMIT_ANSWERS_SIGNAL, {"resume_token": RESUME_TOKEN, "answers": ANSWERS})

        async with probe_worker(env):
            # Auto time-skipping would race past an unbounded wait_condition to
            # the run timeout before the replacement worker finishes replaying.
            with env.auto_time_skipping_disabled():
                result = await asyncio.wait_for(handle.result(), timeout=30)
            history = await handle.fetch_history()

    assert result == ANSWERS
    await Replayer(workflows=[HitlWaitProbeWorkflow]).replay_workflow(history)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_signal_that_beats_the_wait_is_not_lost() -> None:
    """The signal-before-wait race against a real server: signal-with-start
    delivers the answer in the same history event batch that starts the run, so
    the handler sees it with no pause armed and buffers it. The wait must drain
    that buffer rather than parking for a signal that already came and went."""
    from temporalio.worker import Replayer

    from shared.temporal.testing import workflow_environment

    async with workflow_environment() as env:
        async with probe_worker(env):
            handle = await env.client.start_workflow(
                HitlWaitProbeWorkflow.run,
                RESUME_TOKEN,
                id="hitl-wait-probe-early-signal",
                task_queue=WAIT_PROBE_TASK_QUEUE,
                start_signal=SUBMIT_ANSWERS_SIGNAL,
                start_signal_args=[{"resume_token": RESUME_TOKEN, "answers": ANSWERS}],
            )
            with env.auto_time_skipping_disabled():
                result = await asyncio.wait_for(handle.result(), timeout=30)
            history = await handle.fetch_history()

    assert result == ANSWERS
    await Replayer(workflows=[HitlWaitProbeWorkflow]).replay_workflow(history)


def test_probe_workflow_is_a_well_formed_defn_composing_the_mixin() -> None:
    """Not integration-marked on purpose: the tests above cannot run without
    the ephemeral test-server binary, so without this the probe class would be
    unexercised anywhere the download is blocked. Pins that it is a real
    ``@workflow.defn``, registers ``submit_answers`` through the mixin, and
    initializes the mixin's state (it defines no ``__init__`` of its own)."""
    from shared.hitl.testing import assert_workflow_registers_submit_answers, get_workflow_definition

    assert_workflow_registers_submit_answers(HitlWaitProbeWorkflow)

    defn = get_workflow_definition(HitlWaitProbeWorkflow)
    assert defn.name == "HitlWaitProbeWorkflow"
    assert defn.run_fn.__name__ == "run"

    wf = HitlWaitProbeWorkflow()
    assert wf._active_resume_token is None
    assert wf._submitted_answers is None
    assert wf._buffered_signals == {}
    assert callable(wf.wait_for_answers)


def test_probe_workflow_registers_the_parked_state_query() -> None:
    """The no-default tests read the pause through this query, so a probe that
    silently stopped registering it would turn their strongest assertion into a
    connection error rather than a failed claim. Runs in the ordinary suite for
    the same reason as the structural test above."""
    from shared.hitl.testing import get_workflow_definition
    from shared.hitl.tests._wait_probe_workflow import PARKED_STATE_QUERY

    defn = get_workflow_definition(HitlWaitProbeWorkflow)
    assert PARKED_STATE_QUERY == "parked_state"
    assert PARKED_STATE_QUERY in defn.queries
    assert defn.queries[PARKED_STATE_QUERY].name == "parked_state"


def test_parked_state_reports_the_pause_without_leaking_the_answers() -> None:
    """The query reports whether an answer is latched, never what it is. A query
    that returned answer content would be a second way to read the batch out of
    a paused workflow, and this probe exists to prove there is exactly one."""
    wf = HitlWaitProbeWorkflow()

    assert wf.parked_state() == {"active_resume_token": None, "has_submitted_answers": False}

    wf._active_resume_token = RESUME_TOKEN
    wf.submit_answers({"resume_token": RESUME_TOKEN, "answers": ANSWERS})

    state = wf.parked_state()
    assert state == {"active_resume_token": RESUME_TOKEN, "has_submitted_answers": True}
    # The exact-dict assertion above already pins today's shape; this pins the
    # PROPERTY, so a future field carrying answer content fails even if someone
    # updates the literal above to match it.
    assert all(isinstance(value, (str, bool, type(None))) for value in state.values()), (
        f"parked_state grew a structured field that could carry answer content: {state}"
    )
