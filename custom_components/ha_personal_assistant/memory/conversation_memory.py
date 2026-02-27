"""Conversation Memory — per-session chat history with session management."""
from __future__ import annotations

import asyncio
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import sessionmaker

from .models import ConversationSession, ConversationHistory

_LOGGER = logging.getLogger(__name__)


class ConversationMemory:
    """Manages conversation sessions and message history.

    Each Telegram chat maintains an active session. Sessions expire after
    a configurable inactivity timeout (default: 30 minutes). When a session
    expires, history is archived and a fresh session starts.
    """

    def __init__(
        self,
        engine: Any,
        executor: ThreadPoolExecutor,
        session_timeout_minutes: int = 30,
    ) -> None:
        """Initialize conversation memory.

        Args:
            engine: SQLAlchemy engine instance.
            executor: ThreadPoolExecutor for sync DB operations.
            session_timeout_minutes: Inactivity timeout for sessions.
        """
        self._engine = engine
        self._executor = executor
        self._Session = sessionmaker(bind=engine)
        self._timeout = timedelta(minutes=session_timeout_minutes)

    async def get_or_create_session(self, chat_id: int) -> dict[str, Any]:
        """Get the active session for a chat, or create a new one.

        If the current session has expired (inactivity > timeout),
        it is deactivated and a new session is created.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            Session dict with 'id', 'chat_id', 'started_at', 'last_activity'.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, self._get_or_create_session_sync, chat_id
        )

    def _get_or_create_session_sync(self, chat_id: int) -> dict[str, Any]:
        """Synchronous session management."""
        session = self._Session()
        try:
            # Find active session for this chat
            active = (
                session.query(ConversationSession)
                .filter(
                    ConversationSession.chat_id == chat_id,
                    ConversationSession.is_active == True,
                )
                .first()
            )

            now = datetime.utcnow()

            if active:
                # Check if session has expired
                if active.last_activity and (now - active.last_activity) > self._timeout:
                    # Expire the old session
                    active.is_active = False
                    _LOGGER.debug(
                        "Session %s expired for chat %s (inactive for %s)",
                        active.id, chat_id, now - active.last_activity,
                    )
                else:
                    # Update last activity
                    active.last_activity = now
                    session.commit()
                    return {
                        "id": active.id,
                        "chat_id": active.chat_id,
                        "started_at": str(active.started_at),
                        "last_activity": str(active.last_activity),
                    }

            # Create new session
            new_session = ConversationSession(
                id=str(uuid.uuid4()),
                chat_id=chat_id,
                started_at=now,
                last_activity=now,
                is_active=True,
            )
            session.add(new_session)
            session.commit()

            _LOGGER.debug("Created new session %s for chat %s", new_session.id, chat_id)
            return {
                "id": new_session.id,
                "chat_id": new_session.chat_id,
                "started_at": str(new_session.started_at),
                "last_activity": str(new_session.last_activity),
            }
        except Exception as err:
            session.rollback()
            _LOGGER.error("Error managing session: %s", err)
            # Return a transient session on error
            return {
                "id": str(uuid.uuid4()),
                "chat_id": chat_id,
                "started_at": str(datetime.utcnow()),
                "last_activity": str(datetime.utcnow()),
            }
        finally:
            session.close()

    async def add_message(
        self,
        session_id: str,
        chat_id: int,
        role: str,
        content: str,
    ) -> None:
        """Add a message to conversation history.

        Args:
            session_id: Session ID.
            chat_id: Telegram chat ID.
            role: Message role ('user' or 'assistant').
            content: Message content.
        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self._executor,
            self._add_message_sync,
            session_id, chat_id, role, content,
        )

    def _add_message_sync(
        self, session_id: str, chat_id: int, role: str, content: str
    ) -> None:
        """Synchronous message insert."""
        db_session = self._Session()
        try:
            msg = ConversationHistory(
                session_id=session_id,
                chat_id=chat_id,
                role=role,
                content=content,
            )
            db_session.add(msg)
            db_session.commit()
        except Exception as err:
            db_session.rollback()
            _LOGGER.error("Error adding message: %s", err)
        finally:
            db_session.close()

    async def get_session_messages(
        self,
        session_id: str,
        limit: int = 50,
    ) -> list[dict[str, str]]:
        """Get messages for a specific session.

        Args:
            session_id: Session ID.
            limit: Maximum number of messages to return.

        Returns:
            List of message dicts with 'role' and 'content'.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self._get_session_messages_sync,
            session_id, limit,
        )

    def _get_session_messages_sync(
        self, session_id: str, limit: int
    ) -> list[dict[str, str]]:
        """Synchronous message retrieval."""
        db_session = self._Session()
        try:
            messages = (
                db_session.query(ConversationHistory)
                .filter(ConversationHistory.session_id == session_id)
                .order_by(ConversationHistory.timestamp.asc())
                .limit(limit)
                .all()
            )
            return [{"role": m.role, "content": m.content} for m in messages]
        finally:
            db_session.close()

    async def get_recent_messages(
        self,
        chat_id: int,
        limit: int = 20,
    ) -> list[dict[str, str]]:
        """Get recent messages for a chat across all sessions.

        Args:
            chat_id: Telegram chat ID.
            limit: Maximum number of messages.

        Returns:
            List of message dicts.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self._get_recent_messages_sync,
            chat_id, limit,
        )

    def _get_recent_messages_sync(
        self, chat_id: int, limit: int
    ) -> list[dict[str, str]]:
        """Synchronous recent messages retrieval."""
        db_session = self._Session()
        try:
            messages = (
                db_session.query(ConversationHistory)
                .filter(ConversationHistory.chat_id == chat_id)
                .order_by(ConversationHistory.timestamp.desc())
                .limit(limit)
                .all()
            )
            # Reverse to chronological order
            messages.reverse()
            return [{"role": m.role, "content": m.content} for m in messages]
        finally:
            db_session.close()

    async def clear_history(self, chat_id: int | None = None) -> int:
        """Clear conversation history.

        Args:
            chat_id: Optional chat ID to clear. If None, clears all.

        Returns:
            Number of messages deleted.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, self._clear_history_sync, chat_id
        )

    def _clear_history_sync(self, chat_id: int | None) -> int:
        """Synchronous clear."""
        db_session = self._Session()
        try:
            query = db_session.query(ConversationHistory)
            if chat_id is not None:
                query = query.filter(ConversationHistory.chat_id == chat_id)
            count = query.delete()
            db_session.commit()
            return count
        finally:
            db_session.close()
