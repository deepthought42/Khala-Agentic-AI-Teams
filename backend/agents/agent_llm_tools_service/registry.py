"""Built-in registration of LLM tool adapters."""

from __future__ import annotations

from typing import Dict

from agent_llm_tools_service.adapters.base import LlmToolAdapter
from agent_llm_tools_service.adapters.git_adapter import GitToolAdapter

_builtin_adapters: Dict[str, LlmToolAdapter] | None = None


def _ensure_registry() -> Dict[str, LlmToolAdapter]:
    global _builtin_adapters
    if _builtin_adapters is None:
        git = GitToolAdapter()
        _builtin_adapters = {git.tool_id: git}
    return _builtin_adapters


def register_builtin_tools() -> Dict[str, LlmToolAdapter]:
    """Copy of the default tool_id -> adapter map."""
    return _ensure_registry().copy()


def get_default_registry() -> Dict[str, LlmToolAdapter]:
    """Singleton registry used by ``LlmToolsService()`` when no custom registry is passed."""
    return _ensure_registry()
