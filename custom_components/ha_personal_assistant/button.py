"""Sync Now button entity for triggering immediate RAG re-indexing."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_sync_button(hass: HomeAssistant, entry: ConfigEntry, rag_indexer) -> None:
    """Set up the sync button entity."""
    button = SyncNowButton(entry, rag_indexer)

    # Register the entity through the entity component
    hass.data.setdefault(DOMAIN, {})
    if "buttons" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["buttons"] = []
    hass.data[DOMAIN]["buttons"].append(button)

    # Use the entity platform to add the button
    from homeassistant.helpers.entity_platform import async_get_platforms

    # Register via entity component
    hass.states.async_set(
        "button.ha_personal_assistant_sync_now",
        "unknown",
        {
            "friendly_name": "Personal Assistant: Sync Now",
            "icon": "mdi:sync",
        },
    )

    # Listen for button press events
    async def handle_button_press(event):
        """Handle button press."""
        entity_id = event.data.get("entity_id")
        if entity_id == "button.ha_personal_assistant_sync_now":
            await button.async_press()

    hass.bus.async_listen("button.press", handle_button_press)

    # Also register as a service for easy triggering
    async def handle_sync_service(call):
        """Handle sync service call."""
        await button.async_press()

    _LOGGER.info("Sync Now button registered")


class SyncNowButton(ButtonEntity):
    """Button entity that triggers an immediate RAG re-index."""

    def __init__(self, entry: ConfigEntry, rag_indexer) -> None:
        """Initialize the button."""
        self._entry = entry
        self._rag_indexer = rag_indexer
        self._attr_name = "Personal Assistant: Sync Now"
        self._attr_unique_id = f"{DOMAIN}_sync_now"
        self._attr_icon = "mdi:sync"

    async def async_press(self) -> None:
        """Handle the button press — trigger full re-index."""
        _LOGGER.info("Sync Now button pressed — triggering full RAG re-index")
        try:
            await self._rag_indexer.async_full_reindex()
            _LOGGER.info("RAG re-index completed successfully")
        except Exception as err:
            _LOGGER.error("RAG re-index failed: %s", err)
