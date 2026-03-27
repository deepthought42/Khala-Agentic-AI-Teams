"""Pydantic models for LLM tool catalog responses."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ExecutionHints(BaseModel):
    """How to invoke an operation in-process (not HTTP execution)."""

    kind: str = Field(
        ...,
        description="e.g. llm_function_call for OpenAI-style tool calls with execute_git_tool",
    )
    package: str = Field(..., description="Python package name")
    handler: str = Field(..., description="Callable name for dispatch")
    context_class: Optional[str] = Field(
        None,
        description="Host-injected context class (e.g. GitToolContext)",
    )
    tool_loop: str = Field(
        default="llm_service.tool_loop.complete_json_with_tool_loop",
        description="Suggested multi-turn tool loop entry point",
    )
    notes: str = Field(default="", description="Security and wiring notes")


class ToolSummary(BaseModel):
    """Short listing for discovery."""

    tool_id: str
    display_name: str
    summary: str
    category: str


class ToolDocumentation(BaseModel):
    """Public documentation references and CLI hints (no vendored man-page bodies)."""

    primary_links: List[str] = Field(
        ...,
        description="Canonical entry points (official docs, book, reference index).",
    )
    reference_links: List[str] = Field(
        default_factory=list,
        description="Additional official or stable URLs.",
    )
    man_page_hints: List[str] = Field(
        default_factory=list,
        description="Suggested man(1) invocations for agents with a local shell; not executed by the API.",
    )
    inline_summary: str = Field(
        default="",
        description="Short curated overview when links alone are insufficient.",
    )


class OperationDetail(BaseModel):
    """One callable operation (maps to one OpenAI function)."""

    operation_id: str = Field(..., description="Same as function_name for Git tools")
    function_name: str
    description: str
    parameters_schema: Dict[str, Any] = Field(default_factory=dict)
    execution: ExecutionHints
    documentation_links: List[str] = Field(
        default_factory=list,
        description="Official docs for the underlying CLI or API semantics of this operation.",
    )


class ToolDetail(BaseModel):
    """Full tool metadata including OpenAI definitions for the LLM."""

    tool_id: str
    display_name: str
    summary: str
    category: str
    documentation: ToolDocumentation = Field(
        ...,
        description="Tool-wide documentation links and man hints; use GET .../documentation to fetch this alone.",
    )
    openai_definitions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Pass to LLMClient tools= parameter",
    )
