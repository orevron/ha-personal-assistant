"""Home Assistant Personal Assistant integration.

Listens for telegram_text events, processes messages through a LangGraph
ReAct agent with HA tools, RAG, profile learning, and web search.
Responds via telegram_bot.send_message.
"""
from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    DOMAIN,
    DATA_DIR,
    DB_FILENAME,
    CONF_OLLAMA_URL,
    CONF_OLLAMA_MODEL,
    CONF_OLLAMA_EMBEDDING_MODEL,
    CONF_AGENT_PERSONA,
    CONF_SESSION_TIMEOUT_MINUTES,
    CONF_CONTEXT_BUDGET,
    CONF_BLOCKED_KEYWORDS,
    CONFIRMATION_TIMEOUT,
    DEFAULT_OLLAMA_URL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_EMBEDDING_MODEL,
    DEFAULT_AGENT_PERSONA,
    DEFAULT_SESSION_TIMEOUT_MINUTES,
    DEFAULT_CONTEXT_BUDGET,
    AGENT_POOL_MAX_WORKERS,
    AGENT_POOL_THREAD_PREFIX,
    RAG_REINDEX_INTERVAL_HOURS,
    RAG_HISTORY_REINDEX_INTERVAL_HOURS,
)
from .agent.router import LLMRouter
from .agent.graph import PersonalAssistantAgent
from .agent.context_assembler import ContextAssembler, ContextBudget
from .tools.action_policy import ActionPolicy

_LOGGER = logging.getLogger(__name__)

# Dedicated thread pool — never blocks HA's default executor
_AGENT_POOL = ThreadPoolExecutor(
    max_workers=AGENT_POOL_MAX_WORKERS,
    thread_name_prefix=AGENT_POOL_THREAD_PREFIX,
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Personal Assistant from a config entry."""
    config = {**entry.data, **entry.options}

    # Create data directory
    data_dir = hass.config.path(DATA_DIR)
    os.makedirs(data_dir, exist_ok=True)
    db_path = os.path.join(data_dir, DB_FILENAME)

    # Initialize components
    _LOGGER.info("Setting up Personal Assistant integration")

    # 1. LLM Router
    llm_router = LLMRouter(config)
    await llm_router.async_setup()

    # 2. Action Policy
    action_policy = ActionPolicy.from_config(config)

    # 3. Context Assembler
    total_budget = config.get(CONF_CONTEXT_BUDGET, DEFAULT_CONTEXT_BUDGET)
    context_budget = ContextBudget.from_total(total_budget)
    context_assembler = ContextAssembler(budget=context_budget)

    # 4. Tools — import all tool creators
    from .tools.ha_tools import create_ha_tools
    from .tools.profile_tools import create_profile_tools
    from .tools.web_search import create_web_search_tools
    from .tools.rag_tools import create_rag_tools

    # Initialize memory components (Phase 3)
    from .memory.models import async_setup_database
    from .memory.profile_manager import ProfileManager
    from .memory.conversation_memory import ConversationMemory
    from .memory.learning_worker import LearningWorker

    engine = await async_setup_database(db_path, _AGENT_POOL)
    profile_manager = ProfileManager(engine, _AGENT_POOL)
    session_timeout = config.get(CONF_SESSION_TIMEOUT_MINUTES, DEFAULT_SESSION_TIMEOUT_MINUTES)
    conversation_memory = ConversationMemory(engine, _AGENT_POOL, session_timeout)
    learning_worker = LearningWorker(engine, llm_router, profile_manager, _AGENT_POOL)

    # Initialize RAG (Phase 2)
    from .rag.engine import RAGEngine
    from .rag.embeddings import OllamaEmbeddings
    from .rag.indexer import RAGIndexer

    ollama_url = config.get(CONF_OLLAMA_URL, DEFAULT_OLLAMA_URL)
    embedding_model = config.get(CONF_OLLAMA_EMBEDDING_MODEL, DEFAULT_OLLAMA_EMBEDDING_MODEL)
    embeddings = OllamaEmbeddings(base_url=ollama_url, model=embedding_model)
    rag_engine = RAGEngine(db_path, embeddings, _AGENT_POOL)
    await rag_engine.async_setup()
    rag_indexer = RAGIndexer(hass, rag_engine, embeddings, profile_manager)

    # Initialize PII Sanitizer and Content Firewall (Phase 4)
    from .tools.sanitizer import PIISanitizer
    from .tools.content_firewall import ContentFirewall

    blocked_keywords = config.get(CONF_BLOCKED_KEYWORDS, [])
    if isinstance(blocked_keywords, str):
        blocked_keywords = [k.strip() for k in blocked_keywords.split(",") if k.strip()]
    pii_sanitizer = PIISanitizer(blocked_keywords=blocked_keywords)
    content_firewall = ContentFirewall()

    # Create all tools
    ha_tools = create_ha_tools(hass, action_policy)
    profile_tools = create_profile_tools(profile_manager)
    web_search_tools = create_web_search_tools(pii_sanitizer, content_firewall, engine, _AGENT_POOL)
    rag_tools = create_rag_tools(rag_engine, content_firewall)

    all_tools = ha_tools + profile_tools + web_search_tools + rag_tools

    # 5. Agent
    persona = config.get(CONF_AGENT_PERSONA, DEFAULT_AGENT_PERSONA)
    checkpointer_db_path = os.path.join(data_dir, "langgraph_checkpoints.db")
    agent = PersonalAssistantAgent(
        llm_router=llm_router,
        tools=all_tools,
        context_assembler=context_assembler,
        checkpointer_db_path=checkpointer_db_path,
        persona=persona,
    )
    await agent.async_setup()

    # Pending confirmations: chat_id -> asyncio.Event
    pending_confirmations: dict[int, dict[str, Any]] = {}

    # 6. Telegram event listeners
    async def handle_telegram_text(event: Event) -> None:
        """Handle incoming Telegram text messages."""
        chat_id = event.data.get("chat_id")
        text = event.data.get("text", "")
        user_name = event.data.get("from_first", "User")

        if not chat_id or not text:
            return

        _LOGGER.debug("Received Telegram message from %s (chat %s): %s", user_name, chat_id, text[:50])

        try:
            # Get or create conversation session
            session = await conversation_memory.get_or_create_session(chat_id)

            # Gather context
            profile_entries = await profile_manager.get_all_entries()
            ha_entities = _get_relevant_entities(hass, text)
            rag_results = await rag_engine.aretrieve(text)

            # Process through agent
            response = await agent.aprocess_message(
                chat_id=chat_id,
                text=text,
                user_name=user_name,
                conversation_id=session["id"],
                profile_entries=profile_entries,
                ha_entities=ha_entities,
                rag_results=rag_results,
            )

            # Store conversation
            await conversation_memory.add_message(session["id"], chat_id, "user", text)
            await conversation_memory.add_message(session["id"], chat_id, "assistant", response)

            # Log interaction for learning (decoupled, never in response path)
            await learning_worker.queue_interaction(
                session_id=session["id"],
                chat_id=chat_id,
                user_message=text,
                assistant_response=response,
            )

            # Check if agent was interrupted for confirmation
            state = await agent._graph.aget_state(
                {"configurable": {"thread_id": str(chat_id)}}
            )
            if state and state.next:
                # Get the interrupt value
                for task in state.tasks:
                    if hasattr(task, "interrupts") and task.interrupts:
                        for intr in task.interrupts:
                            interrupt_data = intr.value
                            if isinstance(interrupt_data, dict) and interrupt_data.get("type") == "action_confirmation":
                                # Send confirmation keyboard
                                await _send_confirmation_keyboard(
                                    hass, chat_id, interrupt_data.get("message", "Confirm action?")
                                )
                                return

            # Send response via Telegram
            await _send_telegram_message(hass, chat_id, response)

        except Exception as err:
            _LOGGER.error("Error processing message: %s", err, exc_info=True)
            await _send_telegram_message(
                hass, chat_id, "Sorry, I encountered an error processing your message."
            )

    async def handle_telegram_callback(event: Event) -> None:
        """Handle Telegram callback queries (inline keyboard responses)."""
        chat_id = event.data.get("chat_id")
        callback_data = event.data.get("data", "")

        if not chat_id or not callback_data:
            return

        if callback_data.startswith("confirm_"):
            approved = callback_data == "confirm_yes"

            try:
                response = await agent.aresume_with_confirmation(chat_id, approved)

                if response:
                    await _send_telegram_message(hass, chat_id, response)
                else:
                    msg = "✅ Action approved and executed." if approved else "❌ Action cancelled."
                    await _send_telegram_message(hass, chat_id, msg)
            except Exception as err:
                _LOGGER.error("Error handling confirmation: %s", err)
                await _send_telegram_message(hass, chat_id, "Error processing confirmation.")

    async def handle_telegram_command(event: Event) -> None:
        """Handle Telegram commands (e.g., /searchlog)."""
        chat_id = event.data.get("chat_id")
        command = event.data.get("command", "")

        if command == "/searchlog":
            try:
                from .tools.web_search import get_recent_search_log
                log_entries = await get_recent_search_log(engine, _AGENT_POOL, limit=10)
                if log_entries:
                    lines = ["📋 *Recent Search Log:*\n"]
                    for entry in log_entries:
                        status = "🚫 BLOCKED" if entry.get("was_blocked") else "✅"
                        lines.append(
                            f"{status} `{entry.get('sanitized_query', 'N/A')}`"
                            f"\n  _{entry.get('timestamp', 'N/A')}_"
                        )
                    await _send_telegram_message(hass, chat_id, "\n".join(lines))
                else:
                    await _send_telegram_message(hass, chat_id, "No search history found.")
            except Exception as err:
                _LOGGER.error("Error fetching search log: %s", err)
                await _send_telegram_message(hass, chat_id, "Error fetching search log.")

    # Register event listeners
    unsub_text = hass.bus.async_listen("telegram_text", handle_telegram_text)
    unsub_callback = hass.bus.async_listen("telegram_callback", handle_telegram_callback)
    unsub_command = hass.bus.async_listen("telegram_command", handle_telegram_command)

    # 7. Periodic RAG re-indexing
    from datetime import timedelta

    async def _reindex_rag(_now=None) -> None:
        """Periodic RAG re-indexing."""
        try:
            await rag_indexer.async_full_reindex()
            _LOGGER.info("RAG re-indexing completed successfully")
        except Exception as err:
            _LOGGER.error("RAG re-indexing failed: %s", err)

    unsub_reindex = async_track_time_interval(
        hass, _reindex_rag, timedelta(hours=RAG_REINDEX_INTERVAL_HOURS)
    )

    # Initial RAG index on startup
    hass.async_create_task(_reindex_rag())

    # 8. Register sync button entity
    from .button import async_setup_sync_button
    await async_setup_sync_button(hass, entry, rag_indexer)

    # 9. Register HA services
    async def handle_reindex_service(call) -> None:
        """Handle reindex service call."""
        await _reindex_rag()

    async def handle_clear_profile_service(call) -> None:
        """Handle clear profile service call."""
        category = call.data.get("category")
        await profile_manager.clear_entries(category=category)

    async def handle_clear_history_service(call) -> None:
        """Handle clear conversation history service call."""
        chat_id_str = call.data.get("chat_id")
        chat_id = int(chat_id_str) if chat_id_str else None
        await conversation_memory.clear_history(chat_id=chat_id)

    hass.services.async_register(DOMAIN, "reindex", handle_reindex_service)
    hass.services.async_register(DOMAIN, "clear_profile", handle_clear_profile_service)
    hass.services.async_register(DOMAIN, "clear_conversation_history", handle_clear_history_service)

    # 10. Event-driven learner setup (Phase 5)
    from .memory.event_learner import EventLearner
    event_learner = EventLearner(hass, config, profile_manager, llm_router, _AGENT_POOL)
    await event_learner.async_setup()

    # Store references for unload
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "agent": agent,
        "llm_router": llm_router,
        "profile_manager": profile_manager,
        "conversation_memory": conversation_memory,
        "learning_worker": learning_worker,
        "rag_engine": rag_engine,
        "rag_indexer": rag_indexer,
        "event_learner": event_learner,
        "unsub_text": unsub_text,
        "unsub_callback": unsub_callback,
        "unsub_command": unsub_command,
        "unsub_reindex": unsub_reindex,
    }

    _LOGGER.info("Personal Assistant integration setup complete")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    data = hass.data[DOMAIN].pop(entry.entry_id, {})

    # Unsubscribe event listeners
    for key in ["unsub_text", "unsub_callback", "unsub_command", "unsub_reindex"]:
        unsub = data.get(key)
        if unsub:
            unsub()

    # Clean up agent
    agent = data.get("agent")
    if agent:
        await agent.async_close()

    # Stop learning worker
    learning_worker = data.get("learning_worker")
    if learning_worker:
        await learning_worker.async_stop()

    # Stop event learner
    event_learner = data.get("event_learner")
    if event_learner:
        await event_learner.async_stop()

    # Shutdown thread pool
    _AGENT_POOL.shutdown(wait=False)

    _LOGGER.info("Personal Assistant integration unloaded")
    return True


def _get_relevant_entities(hass: HomeAssistant, query: str) -> list[dict[str, Any]]:
    """Get relevant HA entities based on the user's query.

    Uses keyword matching to filter entities that might be relevant.
    """
    query_lower = query.lower()
    query_words = set(query_lower.split())

    # Common HA-related keywords to domain mapping
    domain_keywords = {
        "light": {"light", "lights", "lamp", "lamps", "brightness", "dim", "bright"},
        "switch": {"switch", "switches", "plug", "plugs", "outlet"},
        "climate": {"climate", "temperature", "thermostat", "heating", "cooling", "hvac", "temp", "degrees"},
        "cover": {"cover", "covers", "blind", "blinds", "curtain", "curtains", "shutter", "shutters", "garage"},
        "lock": {"lock", "locks", "door", "unlock"},
        "sensor": {"sensor", "humidity", "pressure", "battery", "power", "energy"},
        "binary_sensor": {"motion", "occupancy", "door", "window", "smoke", "leak"},
        "media_player": {"media", "speaker", "tv", "television", "music", "volume"},
        "camera": {"camera", "cameras"},
        "fan": {"fan", "fans"},
        "vacuum": {"vacuum", "robot"},
    }

    # Determine which domains are relevant
    relevant_domains = set()
    for domain, keywords in domain_keywords.items():
        if query_words & keywords:
            relevant_domains.add(domain)

    # If no specific domain detected, include common ones
    if not relevant_domains:
        relevant_domains = {"light", "switch", "climate", "sensor", "binary_sensor"}

    entities = []
    for state in hass.states.async_all():
        entity_domain = state.entity_id.split(".")[0]
        if entity_domain not in relevant_domains:
            continue

        friendly_name = state.attributes.get("friendly_name", state.entity_id)

        # Check if entity name matches any query words
        name_lower = friendly_name.lower()
        name_words = set(name_lower.split())

        # Include if domain matches or name has overlap with query
        if entity_domain in relevant_domains or query_words & name_words:
            entities.append({
                "entity_id": state.entity_id,
                "state": state.state,
                "friendly_name": friendly_name,
                "area": "",  # Will be enriched if area registry available
            })

    return entities[:50]  # Cap at 50 entities


async def _send_telegram_message(
    hass: HomeAssistant, chat_id: int, message: str
) -> None:
    """Send a message via Telegram with markdown formatting."""
    try:
        await hass.services.async_call(
            "telegram_bot",
            "send_message",
            {
                "message": message,
                "target": chat_id,
                "parse_mode": "markdown",
            },
        )
    except Exception as err:
        _LOGGER.error("Error sending Telegram message: %s", err)
        # Retry without markdown in case formatting causes issues
        try:
            await hass.services.async_call(
                "telegram_bot",
                "send_message",
                {
                    "message": message,
                    "target": chat_id,
                },
            )
        except Exception as err2:
            _LOGGER.error("Failed to send Telegram message even without markdown: %s", err2)


async def _send_confirmation_keyboard(
    hass: HomeAssistant, chat_id: int, message: str
) -> None:
    """Send a Telegram inline keyboard for action confirmation."""
    try:
        await hass.services.async_call(
            "telegram_bot",
            "send_message",
            {
                "message": message,
                "target": chat_id,
                "parse_mode": "markdown",
                "inline_keyboard": [
                    [
                        {"text": "✅ Yes", "callback_data": "confirm_yes"},
                        {"text": "❌ Cancel", "callback_data": "confirm_no"},
                    ]
                ],
            },
        )
    except Exception as err:
        _LOGGER.error("Error sending confirmation keyboard: %s", err)
