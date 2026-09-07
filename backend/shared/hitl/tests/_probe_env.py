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


#: Modules the probe's sandbox must resolve from the host rather than re-import.
#:
#: The temporalio sandbox re-imports the workflow's defining module, and Python
#: imports a module's PARENT PACKAGES first. The probe lives at
#: ``shared.hitl.tests._wait_probe_workflow``, so the sandbox executes
#: ``shared/hitl/__init__.py``, which imports ``validation``, which imports
#: ``fastapi`` at module scope. That drags starlette/anyio/sniffio into the
#: sandbox, where a class subclassing a restriction-proxied object fails with
#: "Restriction state not present. Using subclasses of proxied objects is
#: unsupported."
#:
#: Note where this happens: BEFORE the probe module's own body runs, so the
#: ``workflow.unsafe.imports_passed_through()`` block inside it cannot cover it.
#: A parent package's imports are simply not in scope for that guard. The real
#: production workflow composing this mixin (``PlanningWorkflow``) is unaffected
#: because it lives under ``planning_team``, reaching ``shared.hitl`` only from
#: inside its passthrough block -- this is a consequence of the PROBE's location,
#: not a defect in the mixin.
#:
#: Passing ``fastapi`` through (rather than ``shared.hitl``) is deliberate:
#: passthrough matches by dotted prefix, so ``shared.hitl`` would also pass
#: through ``shared.hitl.tests._wait_probe_workflow`` itself and the probe would
#: stop being sandboxed at all -- gutting the very check this worker exists to
#: run. ``fastapi`` is never touched by a workflow ``run()`` body, which is the
#: same rationale ``shared.temporal.worker._build_workflow_runner`` documents for
#: every module on its own list.
PROBE_PASSTHROUGH_MODULES = ("fastapi",)


def probe_workflow_runner():
    """Build the sandbox runner the probe worker uses.

    Preconditions:
        - None.
    Postconditions:
        - Returns a ``SandboxedWorkflowRunner`` carrying PRODUCTION's passthrough
          configuration (``shared.temporal.worker._build_workflow_runner``, the
          runner every real team worker is built with) plus
          :data:`PROBE_PASSTHROUGH_MODULES`. Building on the production runner
          rather than the SDK default is the point: a probe sandboxed more
          strictly than production would fail on configuration real workflows
          never meet, and one sandboxed more loosely would miss what production
          catches.
        - Still sandboxes the probe workflow module itself -- see
          :data:`PROBE_PASSTHROUGH_MODULES` for why that requires passing
          ``fastapi`` through rather than ``shared.hitl``.
    """
    from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

    from shared.temporal.worker import _build_workflow_runner

    production = _build_workflow_runner()
    return SandboxedWorkflowRunner(
        restrictions=production.restrictions.with_passthrough_modules(*PROBE_PASSTHROUGH_MODULES)
    )


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
