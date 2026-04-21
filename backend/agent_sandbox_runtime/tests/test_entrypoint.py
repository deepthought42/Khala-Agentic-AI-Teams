"""Tests for the single-agent sandbox bootstrap (issue #263).

Covers:
* ``SANDBOX_AGENT_ID`` required — missing env → clean ``SystemExit(2)``.
* Unknown agent id → ``SystemExit(3)`` (registry.get returns None, not raises).
* The single-agent guard middleware: only the bound agent id is invocable;
  same-team sibling agents get 404, not 200.
* ``/health`` returns the bound agent's metadata.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _dummy_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``LLM_PROVIDER=dummy`` so factories don't need a real Ollama."""
    monkeypatch.setenv("LLM_PROVIDER", "dummy")
    from llm_service import _clear_client_cache_for_testing

    _clear_client_cache_for_testing()


def _build_app(monkeypatch: pytest.MonkeyPatch, agent_id: str):
    """Fresh ``_build_app()`` call with the given ``SANDBOX_AGENT_ID``."""
    monkeypatch.setenv("SANDBOX_AGENT_ID", agent_id)
    from agent_sandbox_runtime.entrypoint import _build_app

    return _build_app()


def test_missing_sandbox_agent_id_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SANDBOX_AGENT_ID", raising=False)
    from agent_sandbox_runtime.entrypoint import EXIT_MISSING_ENV, _build_app

    with pytest.raises(SystemExit) as exc_info:
        _build_app()
    assert exc_info.value.code == EXIT_MISSING_ENV


def test_unknown_agent_id_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    """registry.get() returns None for unknown ids — the bootstrap must still
    exit cleanly with ``EXIT_UNKNOWN_AGENT`` rather than AttributeError out."""
    monkeypatch.setenv("SANDBOX_AGENT_ID", "does.not.exist.anywhere")
    from agent_sandbox_runtime.entrypoint import EXIT_UNKNOWN_AGENT, _build_app

    with pytest.raises(SystemExit) as exc_info:
        _build_app()
    assert exc_info.value.code == EXIT_UNKNOWN_AGENT


def test_health_returns_bound_agent_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _build_app(monkeypatch, "blogging.planner")
    client = TestClient(app)

    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["agent_id"] == "blogging.planner"
    assert body["team"] == "blogging"


def test_invoke_bound_agent_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _build_app(monkeypatch, "blogging.planner")
    client = TestClient(app)

    body = {
        "brief": "Test brief about observability.",
        "research_digest": "## Sources\n- Source one: summary.",
        "length_policy_context": "Standard article, ~1000 words.",
    }
    resp = client.post("/_agents/blogging.planner/invoke", json=body)
    assert resp.status_code == 200, resp.text
    envelope = resp.json()
    assert envelope["error"] is None
    assert envelope["output"]["content_plan"]["requirements_analysis"]["plan_acceptable"] is True


def test_invoke_sibling_same_team_agent_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A sandbox bound to ``blogging.planner`` must not serve ``blogging.writer``.

    Without the single-agent guard, the shared shim's team-scoped check would
    accept this request and execute the wrong agent — the bug Codex flagged.
    """
    app = _build_app(monkeypatch, "blogging.planner")
    client = TestClient(app)

    resp = client.post(
        "/_agents/blogging.writer/invoke",
        json={"brief": "x", "research_digest": "x", "length_policy_context": "x"},
    )
    assert resp.status_code == 404
    assert "Sandbox is bound to 'blogging.planner'" in resp.text


def test_invoke_cross_team_agent_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cross-team requests are rejected by the single-agent guard first."""
    app = _build_app(monkeypatch, "blogging.planner")
    client = TestClient(app)

    resp = client.post("/_agents/branding.creative_director/invoke", json={})
    assert resp.status_code == 404
