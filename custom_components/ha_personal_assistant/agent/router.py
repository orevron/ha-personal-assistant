"""LLM Router — selects and configures the appropriate LLM provider."""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel

from ..const import (
    CONF_OLLAMA_URL,
    CONF_OLLAMA_MODEL,
    CONF_CLOUD_LLM_PROVIDER,
    CONF_CLOUD_LLM_API_KEY,
    CONF_CLOUD_LLM_MODEL,
    CONF_CLOUD_LLM_SEND_PROFILE,
    CONF_CLOUD_LLM_SEND_HA_STATE,
    CLOUD_LLM_NONE,
    CLOUD_LLM_OPENAI,
    CLOUD_LLM_GEMINI,
    DEFAULT_OLLAMA_URL,
    DEFAULT_OLLAMA_MODEL,
)

_LOGGER = logging.getLogger(__name__)


class LLMRouter:
    """Routes LLM requests to the appropriate provider.

    Default: Ollama (local). Fallback: optional cloud LLM.
    Exposes a LangChain BaseChatModel with async support.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize the router with config data.

        Args:
            config: Config entry data dict.
        """
        self._config = config
        self._primary_provider = None
        self._fallback_provider = None
        self._primary_llm: BaseChatModel | None = None
        self._fallback_llm: BaseChatModel | None = None
        self._using_cloud = False

    async def async_setup(self) -> None:
        """Set up LLM providers."""
        from ..llm.ollama_provider import OllamaProvider

        # Primary: Ollama
        ollama_url = self._config.get(CONF_OLLAMA_URL, DEFAULT_OLLAMA_URL)
        ollama_model = self._config.get(CONF_OLLAMA_MODEL, DEFAULT_OLLAMA_MODEL)

        self._primary_provider = OllamaProvider(
            base_url=ollama_url,
            model=ollama_model,
        )
        self._primary_llm = self._primary_provider.llm

        # Health check
        if await self._primary_provider.ahealth_check():
            _LOGGER.info("Ollama connection OK at %s (model: %s)", ollama_url, ollama_model)
        else:
            _LOGGER.warning("Ollama at %s is not reachable or model '%s' not available", ollama_url, ollama_model)

        # Fallback: optional cloud LLM
        cloud_provider = self._config.get(CONF_CLOUD_LLM_PROVIDER, CLOUD_LLM_NONE)
        cloud_api_key = self._config.get(CONF_CLOUD_LLM_API_KEY, "")
        cloud_model = self._config.get(CONF_CLOUD_LLM_MODEL, "")

        if cloud_provider == CLOUD_LLM_OPENAI and cloud_api_key:
            from ..llm.openai_provider import OpenAIProvider

            self._fallback_provider = OpenAIProvider(
                api_key=cloud_api_key,
                model=cloud_model or "gpt-4o",
            )
            self._fallback_llm = self._fallback_provider.llm
            _LOGGER.info("OpenAI fallback configured (model: %s)", cloud_model or "gpt-4o")

        elif cloud_provider == CLOUD_LLM_GEMINI and cloud_api_key:
            from ..llm.gemini_provider import GeminiProvider

            self._fallback_provider = GeminiProvider(
                api_key=cloud_api_key,
                model=cloud_model or "gemini-pro",
            )
            self._fallback_llm = self._fallback_provider.llm
            _LOGGER.info("Gemini fallback configured (model: %s)", cloud_model or "gemini-pro")

    def get_llm(self, *, allow_cloud: bool = True) -> BaseChatModel:
        """Get the active LLM.

        Returns the primary (Ollama) LLM. If primary is unavailable and
        a fallback is configured, returns fallback.

        Args:
            allow_cloud: Whether to allow cloud LLM fallback.

        Returns:
            BaseChatModel instance.
        """
        self._using_cloud = False
        if self._primary_llm is not None:
            return self._primary_llm
        if allow_cloud and self._fallback_llm is not None:
            self._using_cloud = True
            _LOGGER.info("Using cloud LLM fallback")
            return self._fallback_llm
        raise RuntimeError("No LLM provider available")

    @property
    def is_using_cloud(self) -> bool:
        """Return True if currently using cloud LLM."""
        return self._using_cloud

    @property
    def should_send_profile(self) -> bool:
        """Check if profile data should be sent to current LLM."""
        if not self._using_cloud:
            return True
        return self._config.get(CONF_CLOUD_LLM_SEND_PROFILE, False)

    @property
    def should_send_ha_state(self) -> bool:
        """Check if HA state should be sent to current LLM."""
        if not self._using_cloud:
            return True
        return self._config.get(CONF_CLOUD_LLM_SEND_HA_STATE, False)

    async def async_health_check(self) -> dict[str, bool]:
        """Run health checks on all configured providers."""
        results = {}
        if self._primary_provider:
            results["ollama"] = await self._primary_provider.ahealth_check()
        if self._fallback_provider:
            provider_name = self._config.get(CONF_CLOUD_LLM_PROVIDER, "cloud")
            results[provider_name] = await self._fallback_provider.ahealth_check()
        return results
