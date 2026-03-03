"""Button entities for the Personal Assistant integration.

Provides a Sync Now button that triggers immediate RAG re-indexing.
Registered as a proper HA platform via async_setup_entry.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _device_info(entry: ConfigEntry) -> dict[str, Any]:
    """Shared device info — must match sensor.py so entities group together."""
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": "Personal Assistant",
        "manufacturer": "HA Personal Assistant",
        "model": "AI Agent",
        "sw_version": "0.1.7",
        "entry_type": None,
    }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the button platform from a config entry."""
    rag_indexer = hass.data[DOMAIN][entry.entry_id]["rag_indexer"]
    async_add_entities([SyncNowButton(entry, rag_indexer)])


class SyncNowButton(ButtonEntity):
    """Button entity that triggers an immediate RAG re-index."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, rag_indexer) -> None:
        """Initialize the button."""
        self._entry = entry
        self._rag_indexer = rag_indexer
        self._attr_name = "Sync Now"
        self._attr_unique_id = f"{DOMAIN}_sync_now"
        self._attr_icon = "mdi:sync"

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info so this button appears on the PA device."""
        return _device_info(self._entry)

    async def async_press(self) -> None:
        """Handle the button press — trigger full re-index."""
        _LOGGER.info("Sync Now button pressed — triggering full RAG re-index")
        try:
            await self._rag_indexer.async_full_reindex()
            _LOGGER.info("RAG re-index completed successfully")
        except Exception as err:
            _LOGGER.error("RAG re-index failed: %s", err)
