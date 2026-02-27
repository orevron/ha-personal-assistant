# Architecture

## System Overview

The Personal Assistant is a Home Assistant custom integration that piggybacks on HA's native Telegram integration for bot management. It listens for `telegram_text` events, processes messages through a LangGraph ReAct agent, and responds via `telegram_bot.send_message`.

## Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         Home Assistant                          │
│                                                                 │
│  ┌──────────────┐    ┌───────────┐    ┌─────────────────────┐  │
│  │ Telegram Bot │───▶│ Event Bus │───▶│  ha_personal_assist │  │
│  │ Integration  │    │           │    │                     │  │
│  └──────────────┘    └───────────┘    │  ┌───────────────┐  │  │
│                                       │  │ Context Assem │  │  │
│                                       │  │ (M9 budget)   │  │  │
│                                       │  └──────┬────────┘  │  │
│                                       │         ▼           │  │
│                                       │  ┌───────────────┐  │  │
│                                       │  │ LangGraph     │  │  │
│                                       │  │ ReAct Agent   │  │  │
│                                       │  └──────┬────────┘  │  │
│                                       │    ┌────┴────┐      │  │
│                                       │    ▼    ▼    ▼      │  │
│                                       │  Tools RAG Profile  │  │
│                                       └─────────────────────┘  │
│                                                                 │
│  ┌────────────────┐  ┌──────────────┐  ┌─────────────────────┐ │
│  │ Ollama (local) │  │ SQLite + vec │  │ InfluxDB (optional) │ │
│  └────────────────┘  └──────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Event Flow

1. **User sends Telegram message** → HA Telegram integration receives it
2. **HA fires `telegram_text` event** with `{chat_id, text, user_id, from_first, ...}`
3. **Our integration's event listener** picks it up in `__init__.py`
4. **Context Assembler (M9)** builds token-budgeted context:
   - Profile subset (relevant entries based on query)
   - HA entity context (keyword/area filtered)
   - Summarized conversation history (LLM-summarized if exceeds budget)
   - RAG top-k results (trimmed to remaining budget)
5. **LangGraph agent runs asynchronously** via `ainvoke()`
6. **Agent reasons and calls tools** through security layers:
   - HA service calls → Action Permission Layer (M7)
   - Web searches → PII Sanitizer (M1) → Content Firewall (M8)
   - RAG retrieval → Content Firewall (M8)
7. **Post-response**: interaction logged to Learning Queue (never in response path)
8. **Response sent** via `hass.services.async_call("telegram_bot", "send_message", ...)`

## Async Execution Model

The integration uses async-native LangGraph and LangChain methods throughout:

- **LLM calls**: `ChatOllama.ainvoke()` — native async via aiohttp
- **Tool execution**: async LangChain tools with `await` for HA API calls
- **Blocking operations**: dedicated `ThreadPoolExecutor` (3 workers) for:
  - SQLite writes (profile, conversation, audit)
  - sqlite-vec operations (embedding storage, KNN search)
  - DuckDuckGo search (synchronous library)
  - Embedding generation (Ollama HTTP calls)

This prevents blocking HA's finite default executor pool.

## LangGraph Agent Structure

```python
StateGraph:
  [agent] ──condition──▶ [tools] ──edge──▶ [agent]
     │                                        │
     └── (no tool calls) ── END               └── (more tool calls) ──▶ [tools]
```

- **Checkpointing**: SQLite-backed via `AsyncSqliteSaver` for interrupt/resume
- **Interrupt flow**: Used for action confirmations on restricted domains
- **State**: `AgentState(messages, user_profile, ha_context, chat_id, conversation_id)`

## Data Storage

Single SQLite database at `{HA_CONFIG}/ha_personal_assistant/assistant.db`:

| Table | Purpose |
|-------|---------|
| `profile_entries` | User preferences, habits, patterns |
| `conversation_sessions` | Session tracking with auto-expiry |
| `conversation_history` | Message archive per session |
| `interaction_log` | Learning pipeline input |
| `search_audit_log` | Web search audit trail |
| `rag_documents` | RAG document metadata |
| `rag_vectors` | sqlite-vec embeddings (virtual table) |

Separate LangGraph checkpoint DB at `langgraph_checkpoints.db`.
