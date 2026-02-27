"""Profile tools — LangChain tools for reading/writing user profile."""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import tool

_LOGGER = logging.getLogger(__name__)


def create_profile_tools(profile_manager: Any) -> list:
    """Create LangChain tools for profile management.

    Args:
        profile_manager: ProfileManager instance.

    Returns:
        List of LangChain tools.
    """

    @tool
    async def get_user_profile(
        category: str = "",
    ) -> str:
        """Get stored user preferences and learned information.

        Returns profile entries that the assistant has learned about the user,
        including preferences, habits, patterns, and facts.

        Args:
            category: Optional filter by category ('preference', 'habit', 'pattern', 'fact').

        Returns:
            JSON with profile entries.
        """
        try:
            entries = await profile_manager.get_all_entries(
                category=category if category else None,
                min_confidence=0.3,
            )

            if not entries:
                return json.dumps({
                    "entries": [],
                    "message": "No profile entries found" + (f" for category '{category}'" if category else ""),
                })

            return json.dumps({"entries": entries}, indent=2, default=str)
        except Exception as err:
            _LOGGER.error("Error getting user profile: %s", err)
            return json.dumps({"error": str(err)})

    @tool
    async def update_user_profile(
        category: str,
        key: str,
        value: str,
        sensitivity: str = "private",
    ) -> str:
        """Store a new learning about the user (preference, habit, or fact).

        Use this when the user explicitly states a preference, habit, or fact
        that should be remembered for future interactions.

        Args:
            category: One of 'preference', 'habit', 'pattern', 'fact'.
            key: A short descriptive key (e.g., 'preferred_temperature', 'wake_time').
            value: The value to store (e.g., '22 degrees', '07:00').
            sensitivity: One of 'public', 'private', 'sensitive'. Default is 'private'.

        Returns:
            Confirmation of the stored entry.
        """
        valid_categories = {"preference", "habit", "pattern", "fact"}
        if category not in valid_categories:
            return json.dumps({
                "error": f"Invalid category '{category}'. Must be one of: {valid_categories}"
            })

        valid_sensitivities = {"public", "private", "sensitive"}
        if sensitivity not in valid_sensitivities:
            sensitivity = "private"

        try:
            entry = await profile_manager.upsert_entry(
                category=category,
                key=key,
                value=value,
                confidence=0.9,  # High confidence for explicitly told info
                sensitivity=sensitivity,
                source="told",
            )
            return json.dumps({
                "status": "success",
                "message": f"Stored: {category}/{key} = {value}",
                "entry": entry,
            }, default=str)
        except Exception as err:
            _LOGGER.error("Error updating profile: %s", err)
            return json.dumps({"error": str(err)})

    return [get_user_profile, update_user_profile]
