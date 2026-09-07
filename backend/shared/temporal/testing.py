"""Shared test-only scaffolding for driving a real ``temporalio`` sandbox.

Not part of ``shared.temporal``'s production public API (see
``shared/temporal/__init__.py``) -- this module is imported only from test
files, several of which drive an actual embedded Temporal test server via
``temporalio.testing.WorkflowEnvironment`` rather than a monkeypatched
``execute_activity``. Before this module existed, each such test file kept
its own byte-for-byte copy of the bootstrap below; this is the single shared
copy.
"""

from __future__ import annotations

import contextlib

import pytest
from temporalio.testing import WorkflowEnvironment

from shared.env import env_flag_opt_in

#: Opt-in strictness for suites whose whole point is the embedded server.
#: ``start_time_skipping`` downloads an ephemeral test-server binary from
#: ``temporal.download`` on first use, and the default behavior below turns a
#: failed download into a ``pytest.skip`` so a developer without egress still
#: gets a usable local suite. That default is wrong for a CI job that exists
#: SOLELY to execute these tests: there, a skip is indistinguishable from a
#: pass, and a proof that silently stops running is not a proof. Setting this
#: makes the download failure fail the run instead. Default-off, so every
#: existing caller keeps today's behavior unchanged.
TEMPORAL_TEST_SERVER_REQUIRED_ENV = "TEMPORAL_TEST_SERVER_REQUIRED"


@contextlib.asynccontextmanager
async def workflow_environment():
    """Start a time-skipping ``WorkflowEnvironment`` with no worker attached.

    Preconditions:
        - Caller is an async test (or other async context) that will drive
          the yielded ``env`` and any workers itself.
    Postconditions:
        - Yields a started ``WorkflowEnvironment``. Skips the test (rather
          than failing) when the ephemeral Temporal test-server binary
          cannot be downloaded (offline CI) -- UNLESS
          ``TEMPORAL_TEST_SERVER_REQUIRED`` is set to a truthy value, in
          which case the underlying ``RuntimeError`` propagates and fails
          the test. The environment is shut down on exit.
    """
    try:
        test_env = await WorkflowEnvironment.start_time_skipping()
    except RuntimeError as exc:
        if env_flag_opt_in(TEMPORAL_TEST_SERVER_REQUIRED_ENV):
            raise
        pytest.skip(f"Temporal ephemeral test server unavailable (no egress?): {exc}")

    async with test_env as env:
        yield env
