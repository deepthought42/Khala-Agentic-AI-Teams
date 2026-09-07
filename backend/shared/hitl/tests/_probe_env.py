"""Shared ``WorkflowEnvironment`` scaffolding for the durable-wait probe tests.

Kept out of ``_wait_probe_workflow`` on purpose: that module is re-imported by
the temporalio workflow sandbox when it loads the workflow class, and it stays
deliberately free of worker/test machinery. This module is imported only from
test files and never from workflow code. The name has no ``test_`` prefix, so
pytest does not collect it.

Preconditions:
    - ``backend/agents`` and ``backend`` are on ``sys.path`` (the ``shared_*``
      convention).
Postconditions:
    - Importing has no side effects beyond function definition.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Dict, List

from shared.hitl.tests._wait_probe_workflow import WAIT_PROBE_TASK_QUEUE, HitlWaitProbeWorkflow

#: The one answer batch every probe test submits and asserts against. Shared so
#: a test cannot "pass" by asserting against a batch it also authored inline
#: with a typo the mixin would have rejected.
ANSWERS: List[Dict[str, Any]] = [{"question_id": "q1", "selected_option_id": "yes", "other_text": None}]


@contextlib.asynccontextmanager
async def probe_worker(env):
    """Run a probe worker against an already-started ``env``.

    Preconditions:
        - ``env`` is a live ``WorkflowEnvironment``.
    Postconditions:
        - Yields once the worker is polling ``WAIT_PROBE_TASK_QUEUE``. Exiting
          stops that worker WITHOUT shutting down ``env``, so a later call can
          start a replacement worker against the same environment -- which is
          how the worker-restart test simulates a worker dying mid-pause.
        - ``max_cached_workflows=0`` disables the sticky cache, so a replacement
          worker rebuilds workflow state by replaying history from event 1
          rather than resuming from an in-memory snapshot. That is what makes
          the restart test a replay test and not merely a reconnect test -- and
          it means every ``parked_state`` query is answered from a fresh replay
          too, so a query result is itself evidence the pause rebuilds.
    """
    from temporalio.worker import Worker

    async with Worker(
        env.client,
        task_queue=WAIT_PROBE_TASK_QUEUE,
        workflows=[HitlWaitProbeWorkflow],
        max_cached_workflows=0,
    ) as worker:
        yield worker


async def wait_until_parked(handle, *, timeout_s: float = 10.0) -> None:
    """Block until history shows the workflow has processed a task and parked.

    Preconditions:
        - ``handle`` is a live workflow handle; ``timeout_s`` is positive.
    Postconditions:
        - Returns once history contains a ``WORKFLOW_TASK_COMPLETED`` event (the
          task in which ``run`` reached ``wait_condition``). Raises
          ``TimeoutError`` naming the observed event types otherwise.
    """
    assert timeout_s > 0, "timeout_s must be positive"

    from temporalio.api.enums.v1 import EventType

    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        events = list((await handle.fetch_history()).events)
        if any(e.event_type == EventType.EVENT_TYPE_WORKFLOW_TASK_COMPLETED for e in events):
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError(
                f"timed out waiting for the probe to park; history event_type ints={[int(e.event_type) for e in events]}"
            )
        await asyncio.sleep(0.05)
