"""Tests for GET /api/llm-tools discovery routes."""

from __future__ import annotations

import sys
from pathlib import Path

_backend = Path(__file__).resolve().parent.parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))
_agents = _backend / "agents"
if str(_agents) not in sys.path:
    sys.path.insert(0, str(_agents))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from unified_api.routes.llm_tools import router as llm_tools_router

app = FastAPI()
app.include_router(llm_tools_router)
client = TestClient(app)


def test_list_llm_tools_returns_git() -> None:
    resp = client.get("/api/llm-tools/")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(t.get("tool_id") == "git" for t in data)


def test_get_git_tool_detail() -> None:
    resp = client.get("/api/llm-tools/git")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tool_id"] == "git"
    assert "openai_definitions" in data
    assert len(data["openai_definitions"]) > 0
    assert "documentation" in data
    assert data["documentation"]["primary_links"]


def test_get_git_operations() -> None:
    resp = client.get("/api/llm-tools/git/operations")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    names = {o["function_name"] for o in data}
    assert "git_status" in names
    assert all("execution" in o for o in data)


def test_unknown_tool_404() -> None:
    resp = client.get("/api/llm-tools/does-not-exist")
    assert resp.status_code == 404


def test_unknown_documentation_404() -> None:
    resp = client.get("/api/llm-tools/does-not-exist/documentation")
    assert resp.status_code == 404
