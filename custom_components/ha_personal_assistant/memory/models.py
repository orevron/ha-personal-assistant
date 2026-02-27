"""SQLAlchemy models and database setup for the Personal Assistant."""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.sql import func

_LOGGER = logging.getLogger(__name__)

Base = declarative_base()


class ProfileEntry(Base):
    """User profile entry model."""

    __tablename__ = "profile_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String, nullable=False)  # 'preference', 'habit', 'pattern', 'fact'
    key = Column(String, nullable=False)
    value = Column(Text, nullable=False)
    confidence = Column(Float, default=0.5)
    sensitivity = Column(String, default="private")  # 'public', 'private', 'sensitive'
    source = Column(String)  # 'observed', 'told', 'inferred'
    first_seen = Column(DateTime, server_default=func.now())
    last_seen = Column(DateTime, server_default=func.now(), onupdate=func.now())
    occurrence_count = Column(Integer, default=1)

    __table_args__ = (UniqueConstraint("category", "key", name="uq_profile_category_key"),)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "category": self.category,
            "key": self.key,
            "value": self.value,
            "confidence": self.confidence,
            "sensitivity": self.sensitivity,
            "source": self.source,
            "first_seen": str(self.first_seen) if self.first_seen else None,
            "last_seen": str(self.last_seen) if self.last_seen else None,
            "occurrence_count": self.occurrence_count,
        }


class ConversationSession(Base):
    """Conversation session model."""

    __tablename__ = "conversation_sessions"

    id = Column(String, primary_key=True)
    chat_id = Column(Integer, nullable=False)
    started_at = Column(DateTime, server_default=func.now())
    last_activity = Column(DateTime, server_default=func.now())
    is_active = Column(Boolean, default=True)


class ConversationHistory(Base):
    """Conversation history message model."""

    __tablename__ = "conversation_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("conversation_sessions.id"), nullable=False)
    chat_id = Column(Integer, nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, server_default=func.now())


class InteractionLog(Base):
    """Interaction log for learning pipeline."""

    __tablename__ = "interaction_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String)
    chat_id = Column(Integer, nullable=False)
    user_message = Column(Text)
    assistant_response = Column(Text)
    tools_used = Column(Text)  # JSON array
    entities_mentioned = Column(Text)  # JSON array
    timestamp = Column(DateTime, server_default=func.now())


class SearchAuditLog(Base):
    """Search audit log for tracking web searches."""

    __tablename__ = "search_audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String)
    original_query = Column(Text, nullable=False)
    sanitized_query = Column(Text, nullable=False)
    was_blocked = Column(Boolean, default=False)
    block_reason = Column(Text)
    timestamp = Column(DateTime, server_default=func.now())


async def async_setup_database(
    db_path: str,
    executor: ThreadPoolExecutor,
) -> Any:
    """Set up the SQLite database and create tables.

    Args:
        db_path: Path to the SQLite database file.
        executor: ThreadPoolExecutor for sync operations.

    Returns:
        SQLAlchemy engine instance.
    """
    loop = asyncio.get_event_loop()

    def _setup_sync():
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        Base.metadata.create_all(engine)
        _LOGGER.info("Database initialized at %s", db_path)
        return engine

    engine = await loop.run_in_executor(executor, _setup_sync)
    return engine
