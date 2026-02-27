# Agent Tools Reference

## Overview

The LangGraph ReAct agent has access to 8 tools for interacting with Home Assistant, searching the web, managing user profiles, and retrieving knowledge.

## HA Tools (`tools/ha_tools.py`)

### `get_ha_entities`

List entities by domain and/or area. Returns a `friendly_name → entity_id` mapping.

- **Parameters:**
  - `domain` (optional): Filter by HA domain (`light`, `switch`, `climate`, etc.)
  - `area` (optional): Filter by area name (`bedroom`, `kitchen`, etc.)
- **Returns:** JSON `{friendly_name: entity_id}` map
- **Security:** No restrictions

### `get_entity_state`

Get current state and attributes of a specific entity.

- **Parameters:**
  - `entity_id` (required): Exact entity ID from `get_ha_entities`
- **Returns:** JSON with state, attributes, last_changed, last_updated
- **Security:** No restrictions

### `call_ha_service`

Call an HA service to control a device. **Goes through Action Permission Layer (M7).**

- **Parameters:**
  - `domain` (required): Service domain (`light`, `lock`, etc.)
  - `service` (required): Service name (`turn_on`, `unlock`, etc.)
  - `entity_id` (optional): Target entity
  - `service_data` (optional): JSON string of extra data
- **Returns:** Status (success/blocked/rejected)
- **Security:** M7 policy check → blocked/allowed/needs confirmation
- **Interrupt:** For restricted domains, uses LangGraph `interrupt()` → Telegram inline keyboard → user confirms/denies → graph resumes

### `get_entity_history`

Get historical states for an entity.

- **Parameters:**
  - `entity_id` (required): Entity to get history for
  - `hours` (optional, default 24): Hours of history
- **Returns:** JSON array of state changes with timestamps

## Web Search (`tools/web_search.py`)

### `search_web`

Search the internet via DuckDuckGo.

- **Parameters:**
  - `query` (required): Search query (must be generic)
- **Returns:** Top-5 results with title, snippet, URL
- **Security pipeline:**
  1. PII Sanitizer (M1) removes personal data
  2. Query logged to `search_audit_log` (M2)
  3. Blocked if too much PII removed
  4. DuckDuckGo search executed
  5. Content Firewall (M8) filters results for injection
- **Agent rule:** Never include personal data, entity IDs, or schedules in queries

## RAG Tools (`tools/rag_tools.py`)

### `retrieve_knowledge`

Search indexed HA data (entities, automations, scenes, history, profile).

- **Parameters:**
  - `query` (required): Natural language query
  - `source_type` (optional): Filter by type (`entity`, `automation`, `scene`, `history`, `profile`)
- **Returns:** Top-5 relevant chunks with content and metadata
- **Security:** Results pass through Content Firewall (M8)

## Profile Tools (`tools/profile_tools.py`)

### `get_user_profile`

Read stored user preferences and learned information.

- **Parameters:**
  - `category` (optional): Filter by `preference`, `habit`, `pattern`, `fact`
- **Returns:** JSON with profile entries (min confidence 0.3)

### `update_user_profile`

Store a new learning about the user.

- **Parameters:**
  - `category` (required): `preference` | `habit` | `pattern` | `fact`
  - `key` (required): Descriptive key (e.g., `preferred_temperature`)
  - `value` (required): Value to store
  - `sensitivity` (optional): `public` | `private` | `sensitive`
- **Returns:** Confirmation with stored entry
- **Note:** Sets confidence to 0.9 and source to `told` for explicit statements

## Permission Layer Behavior

| Domain | Policy | Behavior |
|--------|--------|----------|
| `light`, `switch`, etc. | Allowed | Direct execution |
| `lock`, `camera` | Restricted | Telegram confirmation keyboard |
| `homeassistant` | Blocked | Rejected, agent informed |

## LangGraph Interrupt Flow

```
1. Agent calls call_ha_service(lock.unlock, lock.front_door)
2. Policy detects restricted domain → interrupt()
3. Graph state checkpointed (SQLite)
4. Telegram inline keyboard sent: "Unlock front door? ✅/❌"
5. User taps ✅ → telegram_callback event
6. Graph resumed with approval → service executed
7. (Or: ❌/timeout → resumed with rejection)
```
