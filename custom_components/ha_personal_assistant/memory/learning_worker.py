"""Background Learning Worker — decoupled async learner that processes interaction logs."""
from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy.orm import sessionmaker

from .models import InteractionLog
from .profile_manager import ProfileManager

_LOGGER = logging.getLogger(__name__)


class LearningWorker:
    """Background worker that processes interaction logs asynchronously.

    This is completely decoupled from the response path — interactions are
    queued and the worker processes them at its own pace. This means:
    - Zero added latency to user responses
    - Learning failures don't affect UX
    - Worker processes the queue independently

    Pipeline:
        interaction_log → Queue → Background Learner Worker → Profile updates
    """

    def __init__(
        self,
        engine: Any,
        llm_router: Any,
        profile_manager: ProfileManager,
        executor: ThreadPoolExecutor,
    ) -> None:
        """Initialize the learning worker.

        Args:
            engine: SQLAlchemy engine instance.
            llm_router: LLMRouter for LLM-powered extraction.
            profile_manager: ProfileManager for storing learned entries.
            executor: ThreadPoolExecutor for sync operations.
        """
        self._engine = engine
        self._llm_router = llm_router
        self._profile_manager = profile_manager
        self._executor = executor
        self._Session = sessionmaker(bind=engine)
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._running = False

        # Start the background worker
        self._start_worker()

    def _start_worker(self) -> None:
        """Start the background worker task."""
        self._running = True
        try:
            loop = asyncio.get_event_loop()
            self._task = loop.create_task(self._worker_loop())
        except RuntimeError:
            # No event loop yet, will be started later
            pass

    async def queue_interaction(
        self,
        session_id: str,
        chat_id: int,
        user_message: str,
        assistant_response: str,
        tools_used: list[str] | None = None,
        entities_mentioned: list[str] | None = None,
    ) -> None:
        """Queue an interaction for later processing.

        This returns immediately — never blocks the response path.

        Args:
            session_id: Conversation session ID.
            chat_id: Telegram chat ID.
            user_message: The user's message.
            assistant_response: The assistant's response.
            tools_used: List of tool names used.
            entities_mentioned: List of entity IDs mentioned.
        """
        # Store in DB first (for persistence)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self._executor,
            self._log_interaction_sync,
            session_id, chat_id, user_message, assistant_response,
            tools_used, entities_mentioned,
        )

        # Queue for processing
        await self._queue.put({
            "session_id": session_id,
            "chat_id": chat_id,
            "user_message": user_message,
            "assistant_response": assistant_response,
            "tools_used": tools_used or [],
            "entities_mentioned": entities_mentioned or [],
        })

    def _log_interaction_sync(
        self,
        session_id: str,
        chat_id: int,
        user_message: str,
        assistant_response: str,
        tools_used: list[str] | None,
        entities_mentioned: list[str] | None,
    ) -> None:
        """Synchronous interaction logging."""
        db_session = self._Session()
        try:
            log = InteractionLog(
                session_id=session_id,
                chat_id=chat_id,
                user_message=user_message,
                assistant_response=assistant_response,
                tools_used=json.dumps(tools_used or []),
                entities_mentioned=json.dumps(entities_mentioned or []),
            )
            db_session.add(log)
            db_session.commit()
        except Exception as err:
            db_session.rollback()
            _LOGGER.error("Error logging interaction: %s", err)
        finally:
            db_session.close()

    async def _worker_loop(self) -> None:
        """Background worker loop that processes queued interactions."""
        _LOGGER.info("Learning worker started")

        while self._running:
            try:
                # Wait for an interaction with timeout
                try:
                    interaction = await asyncio.wait_for(
                        self._queue.get(), timeout=60.0
                    )
                except asyncio.TimeoutError:
                    continue

                await self._process_interaction(interaction)
                self._queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.error("Learning worker error: %s", err, exc_info=True)
                await asyncio.sleep(5)  # Back off on error

        _LOGGER.info("Learning worker stopped")

    async def _process_interaction(self, interaction: dict[str, Any]) -> None:
        """Process a single interaction to extract learnable patterns.

        Uses the LLM to analyze the interaction and extract profile entries.

        Args:
            interaction: Interaction dict with user_message, assistant_response, etc.
        """
        try:
            user_msg = interaction["user_message"]
            assistant_resp = interaction["assistant_response"]

            # Use LLM to extract preferences/facts from the interaction
            extraction_prompt = f"""Analyze this interaction and extract any user preferences, habits, or facts.
Return ONLY a JSON array of objects with these fields:
- category: one of 'preference', 'habit', 'pattern', 'fact'
- key: a short descriptive key (e.g., 'preferred_temperature', 'bedtime')
- value: the value (e.g., '22', '23:00')
- confidence: how confident you are (0.0-1.0)
- sensitivity: one of 'public', 'private', 'sensitive'

If there's nothing to learn, return an empty array [].

User: {user_msg}
Assistant: {assistant_resp}

JSON array:"""

            llm = self._llm_router.get_llm(allow_cloud=False)
            response = await llm.ainvoke(extraction_prompt)
            response_text = response.content if hasattr(response, "content") else str(response)

            # Parse the LLM response
            entries = self._parse_extraction(response_text)

            for entry in entries:
                await self._profile_manager.upsert_entry(
                    category=entry["category"],
                    key=entry["key"],
                    value=entry["value"],
                    confidence=entry.get("confidence", 0.5),
                    sensitivity=entry.get("sensitivity", "private"),
                    source="inferred",
                )
                _LOGGER.debug(
                    "Learned: %s/%s = %s (confidence: %.1f)",
                    entry["category"], entry["key"],
                    entry["value"], entry.get("confidence", 0.5),
                )

        except Exception as err:
            _LOGGER.debug("Learning extraction skipped: %s", err)

    def _parse_extraction(self, text: str) -> list[dict[str, Any]]:
        """Parse LLM extraction response into profile entries.

        Args:
            text: LLM response text (expected JSON array).

        Returns:
            List of profile entry dicts.
        """
        # Try to find JSON array in the response
        text = text.strip()

        # Find JSON array boundaries
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or start >= end:
            return []

        json_text = text[start:end + 1]

        try:
            entries = json.loads(json_text)
            if not isinstance(entries, list):
                return []

            # Validate entries
            valid = []
            for e in entries:
                if isinstance(e, dict) and all(k in e for k in ["category", "key", "value"]):
                    if e["category"] in ("preference", "habit", "pattern", "fact"):
                        valid.append(e)
            return valid
        except json.JSONDecodeError:
            return []

    async def async_stop(self) -> None:
        """Stop the background worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
