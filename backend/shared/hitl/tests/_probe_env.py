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


def probe_workflow_runner():
    """Build the sandbox runner the probe worker uses: production's, unmodified.

    The probe is only evidence about production if it runs under production's
    sandbox, so this returns exactly what
    ``shared.temporal.worker._build_workflow_runner`` builds -- the runner every
    real team worker is constructed with -- with NO probe-specific relaxation. A
    probe sandboxed more loosely than production would miss what production
    catches; one sandboxed more strictly would fail on configuration real
    workflows never meet.

    Getting here took a detour worth recording. The temporalio sandbox
    re-imports a workflow's defining module, and Python imports that module's
    PARENT PACKAGES first. The probe lives at
    ``shared.hitl.tests._wait_probe_workflow``, so the sandbox executes
    ``shared/hitl/__init__.py`` -- which used to reach ``fastapi`` through
    ``validation``, dragging starlette/anyio/sniffio in and failing with
    "Restriction state not present. Using subclasses of proxied objects is
    unsupported." Note where that happens: BEFORE the probe module's body runs,
    so the ``workflow.unsafe.imports_passed_through()`` block inside it could
    never have covered it.

    The fix was to stop ``shared.hitl`` importing a web framework at all
    (``validation`` now imports ``HTTPException`` lazily) rather than to hand the
    probe a passthrough exception. A passthrough would have had to name
    ``fastapi`` -- naming ``shared.hitl`` would also pass through
    ``shared.hitl.tests._wait_probe_workflow``, since passthrough matches by
    dotted prefix, and the probe would have stopped being sandboxed at all.
    Fixing the import graph avoids the choice: nothing is excluded here, so the
    probe is sandboxed exactly as production is.

    Preconditions:
        - None.
    Postconditions:
        - Returns production's ``SandboxedWorkflowRunner``. Adds no passthrough
          module of its own; ``test_temporal_signal_replay`` pins that.
    """
    from shared.temporal.worker import _build_workflow_runner

    return _build_workflow_runner()


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
        - Runs under :func:`probe_workflow_runner`, so the workflow is validated
          against production's sandbox configuration rather than the SDK default
          the repo never uses.
    """
    from temporalio.worker import Worker

    async with Worker(
        env.client,
        task_queue=WAIT_PROBE_TASK_QUEUE,
        workflows=[HitlWaitProbeWorkflow],
        workflow_runner=probe_workflow_runner(),
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
