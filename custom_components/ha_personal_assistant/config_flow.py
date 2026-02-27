"""Config flow for the Home Assistant Personal Assistant integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_OLLAMA_URL,
    CONF_OLLAMA_MODEL,
    CONF_OLLAMA_EMBEDDING_MODEL,
    CONF_CLOUD_LLM_PROVIDER,
    CONF_CLOUD_LLM_API_KEY,
    CONF_CLOUD_LLM_MODEL,
    CONF_CLOUD_LLM_SEND_PROFILE,
    CONF_CLOUD_LLM_SEND_HA_STATE,
    CONF_AGENT_PERSONA,
    CONF_INFLUXDB_URL,
    CONF_INFLUXDB_TOKEN,
    CONF_INFLUXDB_ORG,
    CONF_INFLUXDB_BUCKET,
    CONF_BLOCKED_KEYWORDS,
    CONF_SESSION_TIMEOUT_MINUTES,
    CONF_CONTEXT_BUDGET,
    CONF_ALLOWED_DOMAINS,
    CONF_RESTRICTED_DOMAINS,
    CONF_BLOCKED_DOMAINS,
    CONF_REQUIRE_CONFIRMATION_SERVICES,
    DEFAULT_OLLAMA_URL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_EMBEDDING_MODEL,
    DEFAULT_SESSION_TIMEOUT_MINUTES,
    DEFAULT_CONTEXT_BUDGET,
    DEFAULT_INFLUXDB_URL,
    DEFAULT_AGENT_PERSONA,
    DEFAULT_ALLOWED_DOMAINS,
    DEFAULT_RESTRICTED_DOMAINS,
    DEFAULT_BLOCKED_DOMAINS,
    DEFAULT_REQUIRE_CONFIRMATION_SERVICES,
    CLOUD_LLM_NONE,
    CLOUD_LLM_OPENAI,
    CLOUD_LLM_GEMINI,
)

_LOGGER = logging.getLogger(__name__)


async def _test_ollama_connection(url: str) -> bool:
    """Test connection to Ollama server."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{url.rstrip('/')}/api/tags", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                return resp.status == 200
    except Exception:
        return False


class HAPersonalAssistantConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Home Assistant Personal Assistant."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: Ollama configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Test Ollama connection
            if not await _test_ollama_connection(user_input[CONF_OLLAMA_URL]):
                errors["base"] = "cannot_connect_ollama"
            else:
                self._data.update(user_input)
                return await self.async_step_cloud_llm()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_OLLAMA_URL, default=DEFAULT_OLLAMA_URL): str,
                    vol.Required(CONF_OLLAMA_MODEL, default=DEFAULT_OLLAMA_MODEL): str,
                    vol.Required(
                        CONF_OLLAMA_EMBEDDING_MODEL,
                        default=DEFAULT_OLLAMA_EMBEDDING_MODEL,
                    ): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "ollama_url": DEFAULT_OLLAMA_URL,
            },
        )

    async def async_step_cloud_llm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2: Optional cloud LLM configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_persona()

        return self.async_show_form(
            step_id="cloud_llm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CLOUD_LLM_PROVIDER, default=CLOUD_LLM_NONE
                    ): vol.In(
                        {
                            CLOUD_LLM_NONE: "None (Local Ollama Only)",
                            CLOUD_LLM_OPENAI: "OpenAI",
                            CLOUD_LLM_GEMINI: "Google Gemini",
                        }
                    ),
                    vol.Optional(CONF_CLOUD_LLM_API_KEY, default=""): str,
                    vol.Optional(CONF_CLOUD_LLM_MODEL, default=""): str,
                    vol.Optional(
                        CONF_CLOUD_LLM_SEND_PROFILE, default=False
                    ): bool,
                    vol.Optional(
                        CONF_CLOUD_LLM_SEND_HA_STATE, default=False
                    ): bool,
                }
            ),
            errors=errors,
            description_placeholders={},
        )

    async def async_step_persona(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 3: Agent persona and behavior preferences."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_action_policy()

        return self.async_show_form(
            step_id="persona",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_AGENT_PERSONA, default=DEFAULT_AGENT_PERSONA
                    ): str,
                    vol.Optional(
                        CONF_SESSION_TIMEOUT_MINUTES,
                        default=DEFAULT_SESSION_TIMEOUT_MINUTES,
                    ): int,
                    vol.Optional(
                        CONF_CONTEXT_BUDGET, default=DEFAULT_CONTEXT_BUDGET
                    ): int,
                    vol.Optional(CONF_BLOCKED_KEYWORDS, default=""): str,
                }
            ),
        )

    async def async_step_action_policy(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 4: Action policy domain configuration."""
        if user_input is not None:
            # Parse comma-separated lists
            user_input[CONF_RESTRICTED_DOMAINS] = [
                d.strip()
                for d in user_input.get(CONF_RESTRICTED_DOMAINS, "").split(",")
                if d.strip()
            ]
            user_input[CONF_BLOCKED_DOMAINS] = [
                d.strip()
                for d in user_input.get(CONF_BLOCKED_DOMAINS, "").split(",")
                if d.strip()
            ]
            user_input[CONF_REQUIRE_CONFIRMATION_SERVICES] = [
                s.strip()
                for s in user_input.get(CONF_REQUIRE_CONFIRMATION_SERVICES, "").split(",")
                if s.strip()
            ]
            self._data.update(user_input)
            return await self.async_step_influxdb()

        return self.async_show_form(
            step_id="action_policy",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ALLOWED_DOMAINS, default=DEFAULT_ALLOWED_DOMAINS
                    ): str,
                    vol.Optional(
                        CONF_RESTRICTED_DOMAINS,
                        default=", ".join(DEFAULT_RESTRICTED_DOMAINS),
                    ): str,
                    vol.Optional(
                        CONF_BLOCKED_DOMAINS,
                        default=", ".join(DEFAULT_BLOCKED_DOMAINS),
                    ): str,
                    vol.Optional(
                        CONF_REQUIRE_CONFIRMATION_SERVICES,
                        default=", ".join(DEFAULT_REQUIRE_CONFIRMATION_SERVICES),
                    ): str,
                }
            ),
        )

    async def async_step_influxdb(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 5: InfluxDB configuration (for event-driven learning)."""
        if user_input is not None:
            self._data.update(user_input)

            # Parse blocked keywords into a list
            if CONF_BLOCKED_KEYWORDS in self._data:
                kw = self._data[CONF_BLOCKED_KEYWORDS]
                self._data[CONF_BLOCKED_KEYWORDS] = [
                    k.strip() for k in kw.split(",") if k.strip()
                ] if isinstance(kw, str) else kw

            return self.async_create_entry(
                title="Personal Assistant",
                data=self._data,
            )

        return self.async_show_form(
            step_id="influxdb",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_INFLUXDB_URL, default=DEFAULT_INFLUXDB_URL
                    ): str,
                    vol.Optional(CONF_INFLUXDB_TOKEN, default=""): str,
                    vol.Optional(CONF_INFLUXDB_ORG, default=""): str,
                    vol.Optional(CONF_INFLUXDB_BUCKET, default=""): str,
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow handler."""
        return HAPersonalAssistantOptionsFlow(config_entry)


class HAPersonalAssistantOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for reconfiguration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage options."""
        if user_input is not None:
            # Parse lists from comma-separated strings
            for key in [CONF_RESTRICTED_DOMAINS, CONF_BLOCKED_DOMAINS, CONF_REQUIRE_CONFIRMATION_SERVICES]:
                if key in user_input and isinstance(user_input[key], str):
                    user_input[key] = [
                        s.strip() for s in user_input[key].split(",") if s.strip()
                    ]
            if CONF_BLOCKED_KEYWORDS in user_input and isinstance(user_input[CONF_BLOCKED_KEYWORDS], str):
                user_input[CONF_BLOCKED_KEYWORDS] = [
                    k.strip() for k in user_input[CONF_BLOCKED_KEYWORDS].split(",") if k.strip()
                ]
            return self.async_create_entry(title="", data=user_input)

        current = {**self._config_entry.data, **self._config_entry.options}

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_OLLAMA_URL,
                        default=current.get(CONF_OLLAMA_URL, DEFAULT_OLLAMA_URL),
                    ): str,
                    vol.Required(
                        CONF_OLLAMA_MODEL,
                        default=current.get(CONF_OLLAMA_MODEL, DEFAULT_OLLAMA_MODEL),
                    ): str,
                    vol.Optional(
                        CONF_AGENT_PERSONA,
                        default=current.get(CONF_AGENT_PERSONA, DEFAULT_AGENT_PERSONA),
                    ): str,
                    vol.Optional(
                        CONF_SESSION_TIMEOUT_MINUTES,
                        default=current.get(CONF_SESSION_TIMEOUT_MINUTES, DEFAULT_SESSION_TIMEOUT_MINUTES),
                    ): int,
                    vol.Optional(
                        CONF_CONTEXT_BUDGET,
                        default=current.get(CONF_CONTEXT_BUDGET, DEFAULT_CONTEXT_BUDGET),
                    ): int,
                    vol.Optional(
                        CONF_RESTRICTED_DOMAINS,
                        default=", ".join(current.get(CONF_RESTRICTED_DOMAINS, DEFAULT_RESTRICTED_DOMAINS)),
                    ): str,
                    vol.Optional(
                        CONF_BLOCKED_DOMAINS,
                        default=", ".join(current.get(CONF_BLOCKED_DOMAINS, DEFAULT_BLOCKED_DOMAINS)),
                    ): str,
                    vol.Optional(
                        CONF_REQUIRE_CONFIRMATION_SERVICES,
                        default=", ".join(current.get(CONF_REQUIRE_CONFIRMATION_SERVICES, DEFAULT_REQUIRE_CONFIRMATION_SERVICES)),
                    ): str,
                    vol.Optional(
                        CONF_BLOCKED_KEYWORDS,
                        default=", ".join(current.get(CONF_BLOCKED_KEYWORDS, [])),
                    ): str,
                }
            ),
        )
