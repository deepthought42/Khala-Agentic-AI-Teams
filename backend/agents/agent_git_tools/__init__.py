"""Shared OpenAI-style Git tools for any repo-backed agent (backed by SE git_utils).

For discovery of available LLM tools and operations, use ``agent_llm_tools_service.LlmToolsService``
or the unified API ``/api/llm-tools`` routes.
"""

from .context import GitToolContext
from .definitions import GIT_TOOL_DEFINITIONS
from .executor import build_git_tool_handlers, execute_git_tool

__all__ = [
    "GitToolContext",
    "GIT_TOOL_DEFINITIONS",
    "build_git_tool_handlers",
    "execute_git_tool",
]
