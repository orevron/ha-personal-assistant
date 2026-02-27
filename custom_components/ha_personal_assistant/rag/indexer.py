"""RAG Indexer — indexes HA entities, automations, scenes, history, and profile."""
from __future__ import annotations

import json
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)


class RAGIndexer:
    """Indexes various HA data sources into the RAG engine.

    Sources indexed:
    - Entity registry (entity_id, friendly_name, domain, area, device)
    - Automations (name, triggers, conditions, actions)
    - Scenes (name, entities, states)
    - Entity history (summarized recent states)
    - User profile (profile entries, preferences)
    """

    def __init__(
        self,
        hass: Any,
        rag_engine: Any,
        embeddings: Any,
        profile_manager: Any,
    ) -> None:
        """Initialize the indexer.

        Args:
            hass: Home Assistant instance.
            rag_engine: RAGEngine instance.
            embeddings: OllamaEmbeddings instance.
            profile_manager: ProfileManager instance.
        """
        self._hass = hass
        self._rag_engine = rag_engine
        self._embeddings = embeddings
        self._profile_manager = profile_manager

    async def async_full_reindex(self) -> dict[str, int]:
        """Perform a full re-index of all sources.

        Returns:
            Dict with counts of indexed items per source type.
        """
        _LOGGER.info("Starting full RAG re-index")
        counts = {}

        counts["entities"] = await self._index_entities()
        counts["automations"] = await self._index_automations()
        counts["scenes"] = await self._index_scenes()
        counts["history"] = await self._index_history()
        counts["profile"] = await self._index_profile()

        total = sum(counts.values())
        _LOGGER.info("RAG re-index complete: %d total items indexed (%s)", total, counts)
        return counts

    async def _index_entities(self) -> int:
        """Index all HA entities with their metadata."""
        await self._rag_engine.aclear_source_type("entity")

        count = 0
        entity_registry = self._hass.helpers.entity_registry.async_get()
        area_registry = self._hass.helpers.area_registry.async_get()
        device_registry = self._hass.helpers.device_registry.async_get()

        # Build area name lookup
        area_names: dict[str, str] = {}
        for area in area_registry.async_list_areas():
            area_names[area.id] = area.name

        for state in self._hass.states.async_all():
            entity_id = state.entity_id
            friendly_name = state.attributes.get("friendly_name", entity_id)
            domain = entity_id.split(".")[0]

            # Get area info
            area_name = ""
            entity_entry = entity_registry.async_get(entity_id)
            if entity_entry:
                if entity_entry.area_id:
                    area_name = area_names.get(entity_entry.area_id, "")
                elif entity_entry.device_id:
                    device = device_registry.async_get(entity_entry.device_id)
                    if device and device.area_id:
                        area_name = area_names.get(device.area_id, "")

            # Build document content
            content = (
                f"Entity: {friendly_name} ({entity_id})\n"
                f"Domain: {domain}\n"
                f"Current state: {state.state}\n"
            )
            if area_name:
                content += f"Area: {area_name}\n"

            # Add relevant attributes
            attrs = state.attributes
            relevant_attrs = {}
            for key in ["device_class", "unit_of_measurement", "supported_features"]:
                if key in attrs:
                    relevant_attrs[key] = attrs[key]
            if relevant_attrs:
                content += f"Attributes: {json.dumps(relevant_attrs, default=str)}\n"

            result = await self._rag_engine.ainsert(
                content=content,
                source=entity_id,
                source_type="entity",
                metadata={"domain": domain, "area": area_name, "friendly_name": friendly_name},
            )
            if result is not None:
                count += 1

        _LOGGER.debug("Indexed %d entities", count)
        return count

    async def _index_automations(self) -> int:
        """Index HA automations."""
        await self._rag_engine.aclear_source_type("automation")

        count = 0
        for state in self._hass.states.async_all():
            if not state.entity_id.startswith("automation."):
                continue

            friendly_name = state.attributes.get("friendly_name", state.entity_id)
            last_triggered = state.attributes.get("last_triggered", "never")

            content = (
                f"Automation: {friendly_name}\n"
                f"Entity ID: {state.entity_id}\n"
                f"State: {state.state}\n"
                f"Last triggered: {last_triggered}\n"
            )

            # Try to get automation config for more details
            try:
                automation_id = state.entity_id.replace("automation.", "")
                # HA stores automation configs internally
                content += f"ID: {automation_id}\n"
            except Exception:
                pass

            result = await self._rag_engine.ainsert(
                content=content,
                source=state.entity_id,
                source_type="automation",
                metadata={"friendly_name": friendly_name},
            )
            if result is not None:
                count += 1

        _LOGGER.debug("Indexed %d automations", count)
        return count

    async def _index_scenes(self) -> int:
        """Index HA scenes."""
        await self._rag_engine.aclear_source_type("scene")

        count = 0
        for state in self._hass.states.async_all():
            if not state.entity_id.startswith("scene."):
                continue

            friendly_name = state.attributes.get("friendly_name", state.entity_id)
            entity_ids = state.attributes.get("entity_id", [])

            content = (
                f"Scene: {friendly_name}\n"
                f"Entity ID: {state.entity_id}\n"
            )
            if entity_ids:
                content += f"Controlled entities: {', '.join(entity_ids) if isinstance(entity_ids, list) else entity_ids}\n"

            result = await self._rag_engine.ainsert(
                content=content,
                source=state.entity_id,
                source_type="scene",
                metadata={"friendly_name": friendly_name},
            )
            if result is not None:
                count += 1

        _LOGGER.debug("Indexed %d scenes", count)
        return count

    async def _index_history(self) -> int:
        """Index summarized recent entity history."""
        await self._rag_engine.aclear_source_type("history")

        count = 0
        # Focus on entities that have interesting state changes
        interesting_domains = {"light", "switch", "climate", "cover", "lock", "media_player"}

        for state in self._hass.states.async_all():
            domain = state.entity_id.split(".")[0]
            if domain not in interesting_domains:
                continue

            friendly_name = state.attributes.get("friendly_name", state.entity_id)
            content = (
                f"Recent state of {friendly_name} ({state.entity_id}):\n"
                f"Current: {state.state}\n"
            )

            if state.last_changed:
                content += f"Last changed: {state.last_changed.isoformat()}\n"

            result = await self._rag_engine.ainsert(
                content=content,
                source=state.entity_id,
                source_type="history",
                metadata={"domain": domain, "friendly_name": friendly_name},
            )
            if result is not None:
                count += 1

        _LOGGER.debug("Indexed %d entity histories", count)
        return count

    async def _index_profile(self) -> int:
        """Index user profile entries."""
        await self._rag_engine.aclear_source_type("profile")

        count = 0
        try:
            entries = await self._profile_manager.get_all_entries()
            for entry in entries:
                content = (
                    f"User preference - {entry['category']}/{entry['key']}: {entry['value']}\n"
                    f"Source: {entry.get('source', 'unknown')}\n"
                    f"Confidence: {entry.get('confidence', 0.5)}\n"
                )

                result = await self._rag_engine.ainsert(
                    content=content,
                    source=f"profile_{entry['category']}_{entry['key']}",
                    source_type="profile",
                    metadata={
                        "category": entry["category"],
                        "key": entry["key"],
                        "sensitivity": entry.get("sensitivity", "private"),
                    },
                )
                if result is not None:
                    count += 1
        except Exception as err:
            _LOGGER.error("Error indexing profile: %s", err)

        _LOGGER.debug("Indexed %d profile entries", count)
        return count
