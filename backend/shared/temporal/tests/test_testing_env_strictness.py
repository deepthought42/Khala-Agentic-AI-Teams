"""Coverage for ``workflow_environment``'s skip-vs-fail decision.

The helper's default -- turn an unreachable ``temporal.download`` into a
``pytest.skip`` -- exists so a developer without egress still gets a usable
local suite. That default is actively harmful in a CI job whose entire purpose
is to run ``WorkflowEnvironment`` tests: there a skip is indistinguishable from
a pass, and a suite that silently stops running proves nothing.
``TEMPORAL_TEST_SERVER_REQUIRED`` is what CI sets to make the failure loud.

Worth its own tests precisely because it is a test-infrastructure switch:
nothing else fails if it silently stops working. If this flag regressed to
skipping under all conditions, every guarantee downstream of it would keep
reporting green while proving nothing at all.
"""

from __future__ import annotations

import pytest

from shared.temporal import testing as temporal_testing


@pytest.fixture
def unreachable_test_server(monkeypatch):
    """Make ``start_time_skipping`` fail as it does with no egress.

    Preconditions:
        - None.
    Postconditions:
        - ``WorkflowEnvironment.start_time_skipping`` raises ``RuntimeError``
          with a recognizable message, without touching the network.
    """

    async def _boom(*args, **kwargs):
        raise RuntimeError("Failed starting test server: simulated download failure")

    monkeypatch.setattr(temporal_testing.WorkflowEnvironment, "start_time_skipping", _boom)


@pytest.mark.asyncio
async def test_a_download_failure_skips_by_default(unreachable_test_server, monkeypatch) -> None:
    """Unset flag: a developer with no egress gets a skip, not a red suite."""
    monkeypatch.delenv(temporal_testing.TEMPORAL_TEST_SERVER_REQUIRED_ENV, raising=False)

    with pytest.raises(pytest.skip.Exception, match="Temporal ephemeral test server unavailable"):
        async with temporal_testing.workflow_environment():
            pytest.fail("the context manager must not yield when the server cannot start")


@pytest.mark.asyncio
async def test_a_download_failure_raises_when_the_server_is_declared_required(
    unreachable_test_server, monkeypatch
) -> None:
    """Flag set: the original ``RuntimeError`` propagates, so CI goes red rather
    than green-with-skips. Asserts the underlying error survives -- a wrapped or
    replaced exception would lose the download diagnostics that make the failure
    actionable."""
    monkeypatch.setenv(temporal_testing.TEMPORAL_TEST_SERVER_REQUIRED_ENV, "true")

    with pytest.raises(RuntimeError, match="simulated download failure"):
        async with temporal_testing.workflow_environment():
            pytest.fail("the context manager must not yield when the server cannot start")


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["false", "0", "no", "off", "", "yes-ish"])
async def test_only_an_explicit_opt_in_makes_the_server_required(
    unreachable_test_server, monkeypatch, value: str
) -> None:
    """Default-off semantics, spelled out: the flag is a deliberate CI switch, so
    anything short of an explicit truthy value leaves today's skip behavior
    exactly as every existing caller of this helper already relies on."""
    monkeypatch.setenv(temporal_testing.TEMPORAL_TEST_SERVER_REQUIRED_ENV, value)

    with pytest.raises(pytest.skip.Exception):
        async with temporal_testing.workflow_environment():
            pytest.fail("the context manager must not yield when the server cannot start")
