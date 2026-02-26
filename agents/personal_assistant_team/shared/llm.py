"""LLM client wrapper for Personal Assistant team."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Raised when LLM operations fail."""


class LLMClient:
    """
    LLM client for making completions.
    
    Supports Ollama as the primary provider with configurable settings.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 180.0,
        max_retries: int = 3,
    ) -> None:
        """
        Initialize the LLM client.
        
        Args:
            base_url: Ollama base URL. Defaults to SW_LLM_BASE_URL or localhost.
            model: Model name. Defaults to SW_LLM_MODEL.
            timeout: Request timeout in seconds.
            max_retries: Maximum retry attempts.
        """
        self.base_url = base_url or os.getenv("SW_LLM_BASE_URL", "http://127.0.0.1:11434")
        self.model = model or os.getenv("SW_LLM_MODEL", "llama3.2")
        self.timeout = timeout
        self.max_retries = max_retries
        
        self._provider = os.getenv("SW_LLM_PROVIDER", "ollama")
        if self._provider == "dummy":
            logger.warning("Using dummy LLM provider")

    def complete(
        self,
        prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        Generate a text completion.
        
        Args:
            prompt: The prompt to complete
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens to generate
            system_prompt: Optional system prompt
            
        Returns:
            Generated text
        """
        if self._provider == "dummy":
            return self._dummy_complete(prompt)
        
        return self._ollama_complete(
            prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )

    def complete_json(
        self,
        prompt: str,
        *,
        temperature: float = 0.2,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate a JSON completion.
        
        Args:
            prompt: The prompt (should request JSON output)
            temperature: Sampling temperature
            system_prompt: Optional system prompt
            
        Returns:
            Parsed JSON dict
        """
        if self._provider == "dummy":
            return self._dummy_complete_json(prompt)
        
        response = self._ollama_complete(
            prompt,
            temperature=temperature,
            system_prompt=system_prompt,
            json_mode=True,
        )
        
        return self._parse_json(response)

    def _ollama_complete(
        self,
        prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        json_mode: bool = False,
    ) -> str:
        """Make a completion request to Ollama."""
        url = f"{self.base_url}/api/generate"
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }
        
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        
        if system_prompt:
            payload["system"] = system_prompt
        
        if json_mode:
            payload["format"] = "json"
        
        last_error = None
        for attempt in range(self.max_retries):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(url, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    return data.get("response", "")
            except httpx.HTTPError as e:
                last_error = e
                logger.warning("LLM request failed (attempt %d/%d): %s", attempt + 1, self.max_retries, e)
        
        raise LLMError(f"LLM request failed after {self.max_retries} attempts: {last_error}")

    def _parse_json(self, text: str) -> Dict[str, Any]:
        """Parse JSON from LLM response, handling common issues."""
        text = text.strip()
        
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if json_match:
            text = json_match.group(1).strip()
        
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        
        raise LLMError(f"Could not parse JSON from LLM response: {text[:500]}")

    def _dummy_complete(self, prompt: str) -> str:
        """Return a dummy completion for testing."""
        return f"[DUMMY] Response to: {prompt[:100]}..."

    def _dummy_complete_json(self, prompt: str) -> Dict[str, Any]:
        """Return a dummy JSON completion for testing."""
        if "intent" in prompt.lower():
            return {
                "primary_intent": "general",
                "secondary_intents": [],
                "entities": {},
                "confidence": 0.8,
            }
        if "extract" in prompt.lower():
            return {
                "extracted_info": [],
                "reasoning": "Dummy extraction",
            }
        return {"status": "dummy", "message": "This is a test response"}


def get_llm_client(agent_key: Optional[str] = None) -> LLMClient:
    """
    Get an LLM client, optionally configured for a specific agent.
    
    Args:
        agent_key: Optional agent identifier for agent-specific model config.
        
    Returns:
        Configured LLMClient
    """
    model = None
    if agent_key:
        env_key = f"SW_LLM_MODEL_{agent_key}"
        model = os.getenv(env_key)
    
    return LLMClient(model=model)
