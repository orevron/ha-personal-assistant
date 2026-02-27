"""Google Gemini LLM provider wrapper."""
from __future__ import annotations

import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)


class GeminiProvider:
    """Wrapper around ChatGoogleGenerativeAI for cloud LLM inference."""

    def __init__(self, api_key: str, model: str, **kwargs: Any) -> None:
        """Initialize the Gemini provider.

        Args:
            api_key: Google API key.
            model: Model name to use (e.g., 'gemini-pro').
            **kwargs: Additional kwargs passed to ChatGoogleGenerativeAI.
        """
        from langchain_google_genai import ChatGoogleGenerativeAI

        self._llm = ChatGoogleGenerativeAI(
            google_api_key=api_key,
            model=model,
            **kwargs,
        )

    @property
    def llm(self):
        """Return the underlying ChatGoogleGenerativeAI instance."""
        return self._llm

    async def ahealth_check(self) -> bool:
        """Check if Gemini API is reachable."""
        try:
            response = await self._llm.ainvoke("ping")
            return response is not None
        except Exception as err:
            _LOGGER.error("Gemini health check failed: %s", err)
            return False
