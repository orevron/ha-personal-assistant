"""Activity log sensor entities for the Personal Assistant integration."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Maximum length for state values (HA has a 255-char limit)
MAX_STATE_LENGTH = 252  # Leave room for "..."


def _device_info(entry: ConfigEntry) -> dict[str, Any]:
    """Shared device info so all entities group under one device."""
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": "Personal Assistant",
        "manufacturer": "HA Personal Assistant",
        "model": "AI Agent",
        "sw_version": "0.1.7",
        "entry_type": None,
    }


class ActivityLogCoordinator:
    """Lightweight coordinator that tracks the latest agent activity.

    Updated by __init__.py after each Telegram message exchange and
    periodically queried by sensors for their state.
    """

    def __init__(self) -> None:
        """Initialize the coordinator."""
        self._listeners: list[callback] = []
        self.last_user_message: str = ""
        self.last_response: str = ""
        self.last_tools_used: list[str] = []
        self.last_chat_id: int | None = None
        self.last_session_id: str | None = None
        self.last_interaction_ts: datetime | None = None
        self.total_interactions: int = 0
        self.today_interactions: int = 0
        self.status: str = "idle"
        self.last_error: str | None = None
        self._setup_ts = datetime.now(timezone.utc)

    def register_listener(self, listener: callback) -> None:
        """Register a sensor listener for state updates."""
        self._listeners.append(listener)

    def unregister_listener(self, listener: callback) -> None:
        """Remove a sensor listener."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def set_status(self, status: str, error: str | None = None) -> None:
        """Update the agent status and notify listeners."""
        self.status = status
        if error:
            self.last_error = error
        self._notify()

    def record_interaction(
        self,
        user_message: str,
        response: str,
        chat_id: int,
        session_id: str,
        tools_used: list[str] | None = None,
    ) -> None:
        """Record a completed interaction and notify sensors."""
        self.last_user_message = user_message
        self.last_response = response
        self.last_chat_id = chat_id
        self.last_session_id = session_id
        self.last_tools_used = tools_used or []
        self.last_interaction_ts = datetime.now(timezone.utc)
        self.total_interactions += 1
        self.today_interactions += 1
        self.status = "idle"
        self._notify()

    def load_from_db(
        self,
        total_count: int,
        today_count: int,
        last_row: dict[str, Any] | None = None,
    ) -> None:
        """Bootstrap state from the database on startup."""
        self.total_interactions = total_count
        self.today_interactions = today_count
        if last_row:
            self.last_user_message = last_row.get("user_message", "")
            self.last_response = last_row.get("assistant_response", "")
            self.last_chat_id = last_row.get("chat_id")
            self.last_session_id = last_row.get("session_id")
            raw_ts = last_row.get("timestamp")
            if isinstance(raw_ts, str):
                try:
                    self.last_interaction_ts = datetime.fromisoformat(raw_ts)
                except ValueError:
                    pass
            elif isinstance(raw_ts, datetime):
                self.last_interaction_ts = raw_ts
            tools_raw = last_row.get("tools_used", "[]")
            try:
                self.last_tools_used = json.loads(tools_raw) if tools_raw else []
            except (json.JSONDecodeError, TypeError):
                self.last_tools_used = []
        self._notify()

    def _notify(self) -> None:
        """Notify all registered sensor listeners."""
        for listener in self._listeners:
            try:
                listener()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Sensor entities
# ---------------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the activity log sensors from a config entry."""
    coordinator: ActivityLogCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities = [
        LastInteractionSensor(entry, coordinator),
        TotalInteractionsSensor(entry, coordinator),
        LastUserMessageSensor(entry, coordinator),
        LastResponseSensor(entry, coordinator),
        AgentStatusSensor(entry, coordinator),
    ]
    async_add_entities(entities)


# -- Base -------------------------------------------------------------------


class _PASensorBase(SensorEntity):
    """Base class for Personal Assistant sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: ActivityLogCoordinator,
        key: str,
        name: str,
        icon: str,
    ) -> None:
        self._entry = entry
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_{key}"
        self._attr_name = name
        self._attr_icon = icon

    @property
    def device_info(self) -> dict[str, Any]:
        return _device_info(self._entry)

    async def async_added_to_hass(self) -> None:
        """Register listener when entity is added."""
        self._coordinator.register_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister listener when entity is removed."""
        self._coordinator.unregister_listener(self._handle_update)

    @callback
    def _handle_update(self) -> None:
        """React to coordinator data change."""
        self.async_write_ha_state()


# -- Concrete sensors -------------------------------------------------------


class LastInteractionSensor(_PASensorBase):
    """Timestamp of the most recent interaction."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, entry: ConfigEntry, coordinator: ActivityLogCoordinator) -> None:
        super().__init__(entry, coordinator, "last_interaction", "Last Interaction", "mdi:clock-outline")

    @property
    def native_value(self) -> datetime | None:
        return self._coordinator.last_interaction_ts

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._coordinator
        return {
            "user_message": (c.last_user_message or "")[:500],
            "assistant_response": (c.last_response or "")[:500],
            "tools_used": c.last_tools_used,
        }


class TotalInteractionsSensor(_PASensorBase):
    """Cumulative interaction count."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, entry: ConfigEntry, coordinator: ActivityLogCoordinator) -> None:
        super().__init__(entry, coordinator, "total_interactions", "Total Interactions", "mdi:counter")

    @property
    def native_value(self) -> int:
        return self._coordinator.total_interactions

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"today_count": self._coordinator.today_interactions}


class LastUserMessageSensor(_PASensorBase):
    """Most recent user message."""

    def __init__(self, entry: ConfigEntry, coordinator: ActivityLogCoordinator) -> None:
        super().__init__(entry, coordinator, "last_user_message", "Last User Message", "mdi:message-text-outline")

    @property
    def native_value(self) -> str | None:
        msg = self._coordinator.last_user_message
        if not msg:
            return None
        return msg[:MAX_STATE_LENGTH] + "..." if len(msg) > MAX_STATE_LENGTH else msg

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._coordinator
        attrs: dict[str, Any] = {}
        if c.last_user_message:
            attrs["full_message"] = c.last_user_message
        if c.last_chat_id is not None:
            attrs["chat_id"] = c.last_chat_id
        if c.last_session_id:
            attrs["session_id"] = c.last_session_id
        return attrs


class LastResponseSensor(_PASensorBase):
    """Most recent assistant response."""

    def __init__(self, entry: ConfigEntry, coordinator: ActivityLogCoordinator) -> None:
        super().__init__(entry, coordinator, "last_response", "Last Response", "mdi:message-reply-text-outline")

    @property
    def native_value(self) -> str | None:
        msg = self._coordinator.last_response
        if not msg:
            return None
        return msg[:MAX_STATE_LENGTH] + "..." if len(msg) > MAX_STATE_LENGTH else msg

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._coordinator
        attrs: dict[str, Any] = {}
        if c.last_response:
            attrs["full_response"] = c.last_response
        if c.last_tools_used:
            attrs["tools_used"] = c.last_tools_used
        return attrs


class AgentStatusSensor(_PASensorBase):
    """Current agent status (idle / processing / error)."""

    def __init__(self, entry: ConfigEntry, coordinator: ActivityLogCoordinator) -> None:
        super().__init__(entry, coordinator, "status", "Status", "mdi:robot-outline")

    @property
    def native_value(self) -> str:
        return self._coordinator.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._coordinator
        attrs: dict[str, Any] = {}
        if c.last_error:
            attrs["last_error"] = c.last_error
        attrs["uptime"] = str(datetime.now(timezone.utc) - c._setup_ts)
        return attrs
