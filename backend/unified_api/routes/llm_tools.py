"""
Read-only LLM tools catalog for agents and UIs.

- GET /api/llm-tools — list registered tools (summary)
- GET /api/llm-tools/{tool_id} — tool detail including OpenAI tool definitions
- GET /api/llm-tools/{tool_id}/operations — per-function operations and execution hints
- GET /api/llm-tools/{tool_id}/documentation — tool-wide doc links and man hints (no full man text)

Execution remains in-process (e.g. agent_git_tools + GitToolContext); this API is discovery only.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from agent_llm_tools_service import LlmToolNotFoundError, LlmToolsService

router = APIRouter(prefix="/api/llm-tools", tags=["llm-tools"])
_service = LlmToolsService()


@router.get("/")
def list_llm_tools():
    """List all LLM tool bundles (e.g. git)."""
    return [t.model_dump() for t in _service.list_tools()]


@router.get("/{tool_id}/documentation")
def get_llm_tool_documentation(tool_id: str):
    """Return documentation links, optional summary, and man(1) hints (not executed server-side)."""
    try:
        return _service.get_documentation(tool_id).model_dump()
    except LlmToolNotFoundError:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_id}") from None


@router.get("/{tool_id}/operations")
def list_llm_tool_operations(tool_id: str):
    """List callable operations (function names, JSON Schema, execution hints)."""
    try:
        return [op.model_dump() for op in _service.list_operations(tool_id)]
    except LlmToolNotFoundError:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_id}") from None


@router.get("/{tool_id}")
def get_llm_tool(tool_id: str):
    """Return one tool's metadata and full OpenAI-style tool definitions."""
    try:
        return _service.get_tool(tool_id).model_dump()
    except LlmToolNotFoundError:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_id}") from None
