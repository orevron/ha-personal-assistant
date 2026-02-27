"""OpenAI LLM provider wrapper."""
from __future__ import annotations

import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)


class OpenAIProvider:
    """Wrapper around ChatOpenAI for cloud LLM inference."""

    def __init__(self, api_key: str, model: str, **kwargs: Any) -> None:
        """Initialize the OpenAI provider.

        Args:
            api_key: OpenAI API key.
            model: Model name to use (e.g., 'gpt-4o').
            **kwargs: Additional kwargs passed to ChatOpenAI.
        """
        from langchain_openai import ChatOpenAI

        self._llm = ChatOpenAI(
            api_key=api_key,
            model=model,
            **kwargs,
        )

    @property
    def llm(self):
        """Return the underlying ChatOpenAI instance."""
        return self._llm

    async def ahealth_check(self) -> bool:
        """Check if OpenAI API is reachable."""
        try:
            # Simple check — try a minimal completion
            response = await self._llm.ainvoke("ping")
            return response is not None
        except Exception as err:
            _LOGGER.error("OpenAI health check failed: %s", err)
            return False
