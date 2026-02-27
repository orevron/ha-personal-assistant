"""HA Tools — LangChain tools for querying and controlling Home Assistant entities."""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import tool

from .action_policy import ActionPolicy, ActionDecision

_LOGGER = logging.getLogger(__name__)


def create_ha_tools(hass: Any, action_policy: ActionPolicy) -> list:
    """Create LangChain tools for HA interaction.

    Args:
        hass: Home Assistant instance.
        action_policy: ActionPolicy instance for gating service calls.

    Returns:
        List of LangChain tools.
    """

    @tool
    async def get_ha_entities(
        domain: str = "",
        area: str = "",
    ) -> str:
        """List Home Assistant entities, optionally filtered by domain and/or area.

        Returns a mapping of friendly_name -> entity_id for use with other tools.

        Args:
            domain: Optional HA domain to filter by (e.g. 'light', 'switch', 'climate').
            area: Optional area name to filter by (e.g. 'bedroom', 'kitchen').

        Returns:
            JSON mapping of {friendly_name: entity_id}.
        """
        try:
            area_registry = hass.helpers.area_registry.async_get()
            entity_registry = hass.helpers.entity_registry.async_get()
            device_registry = hass.helpers.device_registry.async_get()

            # Build area ID lookup
            area_id_lookup: dict[str, str] = {}
            if area:
                area_lower = area.lower()
                for area_entry in area_registry.async_list_areas():
                    if area_lower in area_entry.name.lower():
                        area_id_lookup[area_entry.id] = area_entry.name

            result: dict[str, str] = {}
            all_states = hass.states.async_all()

            for state in all_states:
                entity_id = state.entity_id
                e_domain = entity_id.split(".")[0]

                # Filter by domain
                if domain and e_domain != domain:
                    continue

                # Filter by area if specified
                if area and area_id_lookup:
                    entity_entry = entity_registry.async_get(entity_id)
                    if entity_entry:
                        # Check entity area directly
                        if entity_entry.area_id and entity_entry.area_id in area_id_lookup:
                            pass  # Match
                        elif entity_entry.device_id:
                            # Check device area
                            device = device_registry.async_get(entity_entry.device_id)
                            if not device or device.area_id not in area_id_lookup:
                                continue
                        else:
                            continue
                    else:
                        continue

                friendly_name = state.attributes.get("friendly_name", entity_id)
                result[friendly_name] = entity_id

            return json.dumps(result, indent=2)
        except Exception as err:
            _LOGGER.error("Error listing HA entities: %s", err)
            return json.dumps({"error": str(err)})

    @tool
    async def get_entity_state(entity_id: str) -> str:
        """Get the current state and attributes of a specific Home Assistant entity.

        Args:
            entity_id: The entity ID (e.g. 'light.living_room').

        Returns:
            JSON with entity state, attributes, and last_changed time.
        """
        try:
            state = hass.states.get(entity_id)
            if state is None:
                return json.dumps({"error": f"Entity '{entity_id}' not found"})

            return json.dumps(
                {
                    "entity_id": entity_id,
                    "state": state.state,
                    "attributes": dict(state.attributes),
                    "last_changed": state.last_changed.isoformat() if state.last_changed else None,
                    "last_updated": state.last_updated.isoformat() if state.last_updated else None,
                },
                default=str,
                indent=2,
            )
        except Exception as err:
            _LOGGER.error("Error getting entity state for %s: %s", entity_id, err)
            return json.dumps({"error": str(err)})

    @tool
    async def call_ha_service(
        domain: str,
        service: str,
        entity_id: str = "",
        service_data: str = "{}",
    ) -> str:
        """Call a Home Assistant service to control a device.

        This goes through the Action Permission Layer. Some services require
        user confirmation and some are blocked entirely.

        You MUST use exact entity_ids from get_ha_entities or get_entity_state.
        NEVER guess or construct an entity_id yourself.

        Args:
            domain: The service domain (e.g. 'light', 'switch', 'climate').
            service: The service to call (e.g. 'turn_on', 'turn_off', 'set_temperature').
            entity_id: Target entity ID.
            service_data: JSON string of additional service data (e.g. '{"brightness": 255}').

        Returns:
            Result string indicating success, need for confirmation, or block.
        """
        from langgraph.types import interrupt

        # Policy check
        check = action_policy.check(domain, service, entity_id)

        if check.decision == ActionDecision.BLOCKED:
            return json.dumps({
                "status": "blocked",
                "reason": check.reason,
            })

        if check.decision == ActionDecision.NEEDS_CONFIRMATION:
            # Use LangGraph interrupt for confirmation flow
            friendly = entity_id.replace("_", " ").split(".")[-1].title() if entity_id else service
            confirmation = interrupt({
                "type": "action_confirmation",
                "domain": domain,
                "service": service,
                "entity_id": entity_id,
                "message": f"🔒 Action requires confirmation:\n*{service.replace('_', ' ').title()}* {friendly}\n\nDo you approve?",
            })

            if not confirmation or not confirmation.get("approved", False):
                return json.dumps({
                    "status": "rejected",
                    "reason": "User declined the action" if confirmation else "Confirmation timed out",
                })

        # Execute the service call
        try:
            data = {}
            if entity_id:
                data["entity_id"] = entity_id
            if service_data and service_data != "{}":
                extra = json.loads(service_data)
                data.update(extra)

            await hass.services.async_call(domain, service, data, blocking=True)
            return json.dumps({
                "status": "success",
                "message": f"Successfully called {domain}.{service}" + (f" on {entity_id}" if entity_id else ""),
            })
        except Exception as err:
            _LOGGER.error("Error calling service %s.%s: %s", domain, service, err)
            return json.dumps({"status": "error", "error": str(err)})

    @tool
    async def get_entity_history(
        entity_id: str,
        hours: int = 24,
    ) -> str:
        """Get historical states for an entity over the specified period.

        Args:
            entity_id: The entity ID to get history for.
            hours: Number of hours of history to retrieve (default: 24).

        Returns:
            JSON array of state changes with timestamps.
        """
        from datetime import datetime, timedelta, timezone

        try:
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(hours=hours)

            # Use HA's internal history component
            history = await hass.async_add_executor_job(
                _get_history_sync, hass, entity_id, start_time, end_time
            )

            if not history or not history[0]:
                return json.dumps({"entity_id": entity_id, "history": [], "message": "No history found"})

            entries = []
            for state in history[0]:
                entries.append({
                    "state": state.state,
                    "last_changed": state.last_changed.isoformat() if state.last_changed else None,
                    "attributes": {
                        k: v for k, v in state.attributes.items()
                        if k in ("friendly_name", "temperature", "brightness", "color_temp")
                    },
                })

            return json.dumps({
                "entity_id": entity_id,
                "period_hours": hours,
                "history": entries,
            }, default=str, indent=2)
        except Exception as err:
            _LOGGER.error("Error getting history for %s: %s", entity_id, err)
            return json.dumps({"error": str(err)})

    return [get_ha_entities, get_entity_state, call_ha_service, get_entity_history]


def _get_history_sync(hass, entity_id, start_time, end_time):
    """Synchronous wrapper for history retrieval."""
    try:
        from homeassistant.components.recorder import history

        return history.state_changes_during_period(
            hass, start_time, end_time, entity_id
        )
    except ImportError:
        _LOGGER.warning("Recorder/history component not available")
        return [[]]
    except Exception as err:
        _LOGGER.error("Error in history retrieval: %s", err)
        return [[]]
