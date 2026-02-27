# RAG & Memory

## RAG Engine

### Overview

The RAG (Retrieval-Augmented Generation) engine uses **sqlite-vec** for vector storage and KNN cosine similarity retrieval. All data lives in a single SQLite database alongside profile and memory tables.

### Why sqlite-vec?

ChromaDB relies on complex C++ bindings that break on HAOS/Alpine Docker. sqlite-vec:
- Lightweight, natively compiled SQLite extension
- Unifies vector + relational data in one DB file
- No external binaries or extra processes
- Works on all HA environments

### Embedding Model

- **Model:** Ollama `nomic-embed-text`
- **Dimension:** 768
- **API:** Ollama `/api/embed` endpoint (async HTTP)

### Indexed Sources

| Source | Content | Refresh Interval |
|--------|---------|-----------------|
| Entity registry | entity_id, friendly_name, domain, area, device | Every 24h |
| Automations | Name, triggers, conditions, actions | Every 24h |
| Scenes | Name, entities, states | Every 24h |
| Entity history | Summarized recent states | Every 24h |
| User profile | Profile entries, preferences | On change |

### Sync Button

A `button.ha_personal_assistant_sync_now` entity is registered in HA. Press it to trigger immediate full re-index of all sources. Can be placed on dashboards or triggered via automation.

### Retrieval

- Top-5 chunks by cosine similarity via sqlite-vec KNN search
- Optional filter by source type
- Results pass through Content Firewall (M8) before reaching the agent

## Profile System

### Data Model

```sql
profile_entries (category, key, value, confidence, sensitivity, source, occurrence_count)
```

- **Categories:** `preference`, `habit`, `pattern`, `fact`
- **Sensitivity:** `public`, `private`, `sensitive` (controls data flow to cloud/web)
- **Source:** `told` (user said), `observed` (detected from events), `inferred` (LLM extracted)
- **Confidence:** 0.0-1.0, increases with repetition, decays over time for unverified patterns

### Profile Manager

CRUD operations with:
- **Upsert:** If category+key exists, updates value and increments occurrence count
- **Confidence boost:** `told` source sets confidence ≥0.9 (user always trusted)
- **Confidence decay:** Periodic decay (×0.95) for `observed`/`inferred` entries that aren't reinforced

## Conversation Memory

### Sessions

Each Telegram chat has an active session. Sessions expire after configurable inactivity (default: 30 min). Expired sessions are archived, fresh session starts.

### Message Storage

Messages stored in `conversation_history` table with session linkage. Used by:
- Context Assembler for building conversation context
- Learning Worker for pattern extraction

## Background Learning Worker

### Architecture

```
Response path:  User msg → Agent → Response (fast, no learning)
Learning path:  interaction_log → Queue → Background Worker → Profile updates
```

### Pipeline

1. Agent completes response → interaction queued (zero latency cost)
2. Background worker picks up from `asyncio.Queue`
3. LLM analyzes the interaction for extractable preferences/facts
4. Valid patterns stored as profile entries with `source: inferred`

### Never in Response Path

The worker runs independently:
- Zero added latency to user responses
- Learning failures don't affect UX
- Worker processes the queue at its own pace

## Event-Driven Behavior Learner

### InfluxDB Integration

Instead of duplicating HA `state_changed` events, queries existing InfluxDB for aggregated state patterns:
- Light usage patterns (when lights go off)
- Climate preferences (temperature settings)
- Door/garage routines (departure/arrival times)
- Media player usage (TV schedules)

### Detection Flow

Every 24 hours:
1. Run Flux queries against InfluxDB for each pattern type
2. LLM analyzes aggregated CSV data for recurring patterns
3. Consistent patterns (≥4/7 days) stored as profile entries with `source: observed`
4. Confidence increases with repeated observations, decays if pattern breaks
