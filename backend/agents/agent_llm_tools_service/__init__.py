"""
LLM tools discovery service: list tools and operations for agents choosing LLM function calls.

First registered tool: Git (see ``agent_git_tools``). Use ``LlmToolsService`` for in-process
discovery; HTTP routes live under the unified API ``/api/llm-tools``.
"""

from agent_llm_tools_service.models import (
    ExecutionHints,
    OperationDetail,
    ToolDetail,
    ToolDocumentation,
    ToolSummary,
)
from agent_llm_tools_service.registry import get_default_registry, register_builtin_tools
from agent_llm_tools_service.service import LlmToolNotFoundError, LlmToolsService

__all__ = [
    "ExecutionHints",
    "LlmToolNotFoundError",
    "LlmToolsService",
    "OperationDetail",
    "ToolDetail",
    "ToolDocumentation",
    "ToolSummary",
    "get_default_registry",
    "register_builtin_tools",
]
