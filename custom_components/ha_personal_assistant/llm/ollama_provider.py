"""Ollama LLM provider wrapper."""
from __future__ import annotations

import logging
from typing import Any

from langchain_ollama import ChatOllama

_LOGGER = logging.getLogger(__name__)


class OllamaProvider:
    """Wrapper around ChatOllama for local LLM inference."""

    def __init__(self, base_url: str, model: str, **kwargs: Any) -> None:
        """Initialize the Ollama provider.

        Args:
            base_url: URL of the Ollama server.
            model: Model name to use.
            **kwargs: Additional kwargs passed to ChatOllama.
        """
        self._base_url = base_url
        self._model = model
        self._llm = ChatOllama(
            base_url=base_url,
            model=model,
            **kwargs,
        )

    @property
    def llm(self) -> ChatOllama:
        """Return the underlying ChatOllama instance."""
        return self._llm

    async def ahealth_check(self) -> bool:
        """Check if the Ollama server is reachable and the model is available."""
        import aiohttp

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._base_url.rstrip('/')}/api/tags",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return False
                    data = await resp.json()
                    models = [m.get("name", "") for m in data.get("models", [])]
                    # Check if our model is available (with or without tag)
                    model_base = self._model.split(":")[0]
                    available = any(
                        m == self._model or m.startswith(f"{model_base}:")
                        for m in models
                    )
                    if not available:
                        _LOGGER.warning(
                            "Model '%s' not found on Ollama server. Available: %s",
                            self._model,
                            models,
                        )
                    return available
        except Exception as err:
            _LOGGER.error("Ollama health check failed: %s", err)
            return False
