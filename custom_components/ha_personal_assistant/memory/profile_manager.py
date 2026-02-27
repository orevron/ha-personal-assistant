"""Profile Manager — CRUD operations for user profile entries."""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from sqlalchemy.orm import sessionmaker

from .models import ProfileEntry

_LOGGER = logging.getLogger(__name__)


class ProfileManager:
    """Manages user profile entries in the SQLite database.

    Supports CRUD operations for profile entries with categories:
    - preference: User-stated preferences (e.g., preferred temperature)
    - habit: Observed habits (e.g., bedtime routine)
    - pattern: Detected pattern (e.g., regular schedules)
    - fact: Factual information (e.g., number of family members)
    """

    def __init__(self, engine: Any, executor: ThreadPoolExecutor) -> None:
        """Initialize the profile manager.

        Args:
            engine: SQLAlchemy engine instance.
            executor: ThreadPoolExecutor for sync DB operations.
        """
        self._engine = engine
        self._executor = executor
        self._Session = sessionmaker(bind=engine)

    async def get_all_entries(
        self,
        category: str | None = None,
        min_confidence: float = 0.0,
        sensitivity_filter: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get all profile entries, optionally filtered.

        Args:
            category: Optional category filter.
            min_confidence: Minimum confidence threshold.
            sensitivity_filter: List of allowed sensitivity levels.

        Returns:
            List of profile entry dicts.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self._get_all_entries_sync,
            category, min_confidence, sensitivity_filter,
        )

    def _get_all_entries_sync(
        self,
        category: str | None,
        min_confidence: float,
        sensitivity_filter: list[str] | None,
    ) -> list[dict[str, Any]]:
        """Synchronous get all entries."""
        session = self._Session()
        try:
            query = session.query(ProfileEntry)
            if category:
                query = query.filter(ProfileEntry.category == category)
            if min_confidence > 0:
                query = query.filter(ProfileEntry.confidence >= min_confidence)
            if sensitivity_filter:
                query = query.filter(ProfileEntry.sensitivity.in_(sensitivity_filter))

            entries = query.order_by(ProfileEntry.confidence.desc()).all()
            return [e.to_dict() for e in entries]
        finally:
            session.close()

    async def upsert_entry(
        self,
        category: str,
        key: str,
        value: str,
        confidence: float = 0.5,
        sensitivity: str = "private",
        source: str = "told",
    ) -> dict[str, Any]:
        """Insert or update a profile entry.

        If an entry with the same category+key exists, updates it and
        increases the occurrence count.

        Args:
            category: Entry category.
            key: Entry key.
            value: Entry value.
            confidence: Confidence score (0.0-1.0).
            sensitivity: Sensitivity level ('public', 'private', 'sensitive').
            source: How the information was obtained ('told', 'observed', 'inferred').

        Returns:
            Updated profile entry dict.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self._upsert_entry_sync,
            category, key, value, confidence, sensitivity, source,
        )

    def _upsert_entry_sync(
        self,
        category: str,
        key: str,
        value: str,
        confidence: float,
        sensitivity: str,
        source: str,
    ) -> dict[str, Any]:
        """Synchronous upsert."""
        session = self._Session()
        try:
            existing = (
                session.query(ProfileEntry)
                .filter(ProfileEntry.category == category, ProfileEntry.key == key)
                .first()
            )

            if existing:
                existing.value = value
                existing.confidence = min(1.0, max(confidence, existing.confidence))
                existing.last_seen = datetime.utcnow()
                existing.occurrence_count += 1
                if source == "told":
                    existing.source = source  # User tells always overrides
                    existing.confidence = max(0.9, existing.confidence)
                session.commit()
                return existing.to_dict()
            else:
                entry = ProfileEntry(
                    category=category,
                    key=key,
                    value=value,
                    confidence=confidence,
                    sensitivity=sensitivity,
                    source=source,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                )
                session.add(entry)
                session.commit()
                return entry.to_dict()
        except Exception as err:
            session.rollback()
            _LOGGER.error("Error upserting profile entry: %s", err)
            raise
        finally:
            session.close()

    async def delete_entry(self, category: str, key: str) -> bool:
        """Delete a specific profile entry.

        Args:
            category: Entry category.
            key: Entry key.

        Returns:
            True if entry was deleted.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, self._delete_entry_sync, category, key
        )

    def _delete_entry_sync(self, category: str, key: str) -> bool:
        """Synchronous delete."""
        session = self._Session()
        try:
            deleted = (
                session.query(ProfileEntry)
                .filter(ProfileEntry.category == category, ProfileEntry.key == key)
                .delete()
            )
            session.commit()
            return deleted > 0
        finally:
            session.close()

    async def clear_entries(self, category: str | None = None) -> int:
        """Clear profile entries.

        Args:
            category: Optional category to clear. If None, clears all.

        Returns:
            Number of entries deleted.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, self._clear_entries_sync, category
        )

    def _clear_entries_sync(self, category: str | None) -> int:
        """Synchronous clear."""
        session = self._Session()
        try:
            query = session.query(ProfileEntry)
            if category:
                query = query.filter(ProfileEntry.category == category)
            count = query.delete()
            session.commit()
            return count
        finally:
            session.close()

    async def decay_confidence(self, decay_factor: float = 0.95) -> None:
        """Decay confidence of observed/inferred entries over time.

        Called periodically to reduce confidence of patterns that
        haven't been reinforced.

        Args:
            decay_factor: Multiplicative decay factor (0.0-1.0).
        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self._executor, self._decay_confidence_sync, decay_factor
        )

    def _decay_confidence_sync(self, decay_factor: float) -> None:
        """Synchronous decay."""
        session = self._Session()
        try:
            entries = (
                session.query(ProfileEntry)
                .filter(ProfileEntry.source.in_(["observed", "inferred"]))
                .all()
            )
            for entry in entries:
                entry.confidence = max(0.1, entry.confidence * decay_factor)
            session.commit()
            _LOGGER.debug("Decayed confidence for %d entries", len(entries))
        finally:
            session.close()
