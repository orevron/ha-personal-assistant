"""Event-Driven Behavior Learner — observes HA state changes via InfluxDB.

Learns user behavior patterns by querying InfluxDB for historical state
changes and detecting patterns like regular schedules, preferred settings,
and daily routines.
"""
from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .profile_manager import ProfileManager

_LOGGER = logging.getLogger(__name__)


class EventLearner:
    """Observes HA events via InfluxDB and learns user behavior patterns.

    Instead of duplicating state_changed events, leverages the existing
    InfluxDB instance that already stores all HA state data. Periodically
    queries InfluxDB for patterns and uses LLM to extract learnable insights.

    Patterns detected:
    - Time-based routines (lights off at 11 PM, garage door at 7:30 AM)
    - Temperature preferences (climate set to 22°C every night)
    - Media patterns (TV on weekdays at 7 PM)
    - Occupancy patterns (who's home when)
    """

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict[str, Any],
        profile_manager: ProfileManager,
        llm_router: Any,
        executor: ThreadPoolExecutor,
    ) -> None:
        """Initialize the event learner.

        Args:
            hass: Home Assistant instance.
            config: Config entry data dict.
            profile_manager: ProfileManager for storing detected patterns.
            llm_router: LLM router for pattern analysis.
            executor: ThreadPoolExecutor for sync operations.
        """
        from ..const import (
            CONF_INFLUXDB_URL,
            CONF_INFLUXDB_TOKEN,
            CONF_INFLUXDB_ORG,
            CONF_INFLUXDB_BUCKET,
            DEFAULT_INFLUXDB_URL,
        )

        self._hass = hass
        self._profile_manager = profile_manager
        self._llm_router = llm_router
        self._executor = executor
        self._unsub_timer = None

        # InfluxDB config
        self._influxdb_url = config.get(CONF_INFLUXDB_URL, DEFAULT_INFLUXDB_URL)
        self._influxdb_token = config.get(CONF_INFLUXDB_TOKEN, "")
        self._influxdb_org = config.get(CONF_INFLUXDB_ORG, "")
        self._influxdb_bucket = config.get(CONF_INFLUXDB_BUCKET, "")

        # Whether InfluxDB is configured
        self._enabled = bool(self._influxdb_url and self._influxdb_token)

    async def async_setup(self) -> None:
        """Set up the event learner with periodic pattern detection."""
        if not self._enabled:
            _LOGGER.info("Event learner disabled — InfluxDB not configured")
            return

        # Run pattern detection every 24 hours
        self._unsub_timer = async_track_time_interval(
            self._hass,
            self._async_detect_patterns,
            timedelta(hours=24),
        )

        # Initial run after 5 minutes (let HA stabilize first)
        self._hass.loop.call_later(
            300,
            lambda: self._hass.async_create_task(self._async_detect_patterns()),
        )

        _LOGGER.info("Event learner initialized (InfluxDB: %s)", self._influxdb_url)

    async def _async_detect_patterns(self, _now=None) -> None:
        """Run pattern detection on InfluxDB data."""
        _LOGGER.info("Starting pattern detection from InfluxDB data")

        try:
            # Define Flux queries for different pattern types
            queries = [
                self._build_light_pattern_query(),
                self._build_climate_pattern_query(),
                self._build_door_pattern_query(),
                self._build_media_pattern_query(),
            ]

            for query_info in queries:
                if query_info is None:
                    continue
                name, flux_query = query_info
                try:
                    data = await self._execute_flux_query(flux_query)
                    if data:
                        await self._analyze_pattern(name, data)
                except Exception as err:
                    _LOGGER.debug("Pattern query '%s' failed: %s", name, err)

        except Exception as err:
            _LOGGER.error("Pattern detection error: %s", err)

    def _build_light_pattern_query(self) -> tuple[str, str] | None:
        """Build a Flux query to detect light usage patterns."""
        if not self._influxdb_bucket:
            return None

        query = f"""
from(bucket: "{self._influxdb_bucket}")
  |> range(start: -7d)
  |> filter(fn: (r) => r["domain"] == "light")
  |> filter(fn: (r) => r["_field"] == "state")
  |> filter(fn: (r) => r["_value"] == "off")
  |> aggregateWindow(every: 1h, fn: count, createEmpty: false)
  |> group(columns: ["entity_id"])
  |> sort(columns: ["_time"])
"""
        return ("light_patterns", query)

    def _build_climate_pattern_query(self) -> tuple[str, str] | None:
        """Build a Flux query to detect climate/temperature patterns."""
        if not self._influxdb_bucket:
            return None

        query = f"""
from(bucket: "{self._influxdb_bucket}")
  |> range(start: -7d)
  |> filter(fn: (r) => r["domain"] == "climate")
  |> filter(fn: (r) => r["_field"] == "temperature")
  |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
  |> group(columns: ["entity_id"])
"""
        return ("climate_patterns", query)

    def _build_door_pattern_query(self) -> tuple[str, str] | None:
        """Build a Flux query to detect door/garage patterns."""
        if not self._influxdb_bucket:
            return None

        query = f"""
from(bucket: "{self._influxdb_bucket}")
  |> range(start: -7d)
  |> filter(fn: (r) => r["domain"] == "cover" or r["domain"] == "lock")
  |> filter(fn: (r) => r["_field"] == "state")
  |> aggregateWindow(every: 1h, fn: count, createEmpty: false)
  |> group(columns: ["entity_id"])
"""
        return ("door_patterns", query)

    def _build_media_pattern_query(self) -> tuple[str, str] | None:
        """Build a Flux query to detect media usage patterns."""
        if not self._influxdb_bucket:
            return None

        query = f"""
from(bucket: "{self._influxdb_bucket}")
  |> range(start: -7d)
  |> filter(fn: (r) => r["domain"] == "media_player")
  |> filter(fn: (r) => r["_field"] == "state")
  |> filter(fn: (r) => r["_value"] == "playing" or r["_value"] == "on")
  |> aggregateWindow(every: 1h, fn: count, createEmpty: false)
  |> group(columns: ["entity_id"])
"""
        return ("media_patterns", query)

    async def _execute_flux_query(self, query: str) -> str:
        """Execute a Flux query against InfluxDB.

        Args:
            query: Flux query string.

        Returns:
            CSV response data as string.
        """
        url = f"{self._influxdb_url.rstrip('/')}/api/v2/query"
        headers = {
            "Authorization": f"Token {self._influxdb_token}",
            "Content-Type": "application/vnd.flux",
            "Accept": "application/csv",
        }
        params = {"org": self._influxdb_org}

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers=headers,
                params=params,
                data=query,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    _LOGGER.warning("InfluxDB query error (%d): %s", resp.status, error_text[:200])
                    return ""
                return await resp.text()

    async def _analyze_pattern(self, pattern_name: str, data: str) -> None:
        """Use LLM to analyze aggregated data and extract patterns.

        Args:
            pattern_name: Name of the pattern type.
            data: CSV data from InfluxDB.
        """
        if not data or len(data) < 50:
            return

        # Truncate data if too long
        if len(data) > 3000:
            data = data[:3000] + "\n... (truncated)"

        prompt = f"""Analyze this Home Assistant {pattern_name} data and identify recurring patterns or habits.

Data (CSV format from InfluxDB):
{data}

Extract patterns as a JSON array with these fields:
- category: one of 'habit', 'pattern'
- key: descriptive key (e.g., 'bedtime_lights_off', 'preferred_night_temp')
- value: the observed value (e.g., '23:00', '22')
- confidence: how confident you are (0.0-1.0)

Rules:
- Only report patterns that appear consistently (at least 4 out of 7 days)
- Focus on timing patterns and preferred settings
- Ignore one-off events

If no clear patterns, return an empty array [].

JSON array:"""

        try:
            llm = self._llm_router.get_llm(allow_cloud=False)
            response = await llm.ainvoke(prompt)
            response_text = response.content if hasattr(response, "content") else str(response)

            # Parse patterns
            entries = self._parse_patterns(response_text)

            for entry in entries:
                await self._profile_manager.upsert_entry(
                    category=entry.get("category", "pattern"),
                    key=entry["key"],
                    value=entry["value"],
                    confidence=entry.get("confidence", 0.5),
                    sensitivity="private",
                    source="observed",
                )
                _LOGGER.info(
                    "Detected pattern: %s = %s (confidence: %.1f)",
                    entry["key"], entry["value"], entry.get("confidence", 0.5),
                )

        except Exception as err:
            _LOGGER.debug("Pattern analysis failed for %s: %s", pattern_name, err)

    def _parse_patterns(self, text: str) -> list[dict[str, Any]]:
        """Parse LLM pattern analysis response."""
        text = text.strip()
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or start >= end:
            return []

        try:
            entries = json.loads(text[start:end + 1])
            if not isinstance(entries, list):
                return []
            return [
                e for e in entries
                if isinstance(e, dict) and "key" in e and "value" in e
            ]
        except json.JSONDecodeError:
            return []

    async def async_stop(self) -> None:
        """Stop the event learner."""
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        _LOGGER.info("Event learner stopped")
