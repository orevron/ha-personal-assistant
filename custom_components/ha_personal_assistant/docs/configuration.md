# Configuration

## Config Flow Steps

The integration uses a 5-step UI-based configuration flow:

### Step 1: Ollama Configuration

| Field | Default | Description |
|-------|---------|-------------|
| Ollama Server URL | `http://192.168.1.97:11434` | URL of your Ollama server |
| Ollama Model | `gpt-oss:20b` | LLM model for the agent |
| Embedding Model | `nomic-embed-text` | Model for RAG embeddings |

The flow tests the Ollama connection before proceeding.

### Step 2: Cloud LLM (Optional)

| Field | Default | Description |
|-------|---------|-------------|
| Provider | None | None / OpenAI / Google Gemini |
| API Key | — | Cloud LLM API key |
| Model Name | — | Cloud model (e.g., `gpt-4o`, `gemini-pro`) |
| Send profile data | ❌ | Whether to include profile in cloud requests |
| Send HA state | ❌ | Whether to include HA state in cloud requests |

⚠️ Cloud LLMs send conversation data to external servers.

### Step 3: Agent Persona

| Field | Default | Description |
|-------|---------|-------------|
| Persona | (built-in) | Custom system prompt for agent personality |
| Session Timeout | 30 min | Inactivity timeout for conversation sessions |
| Context Budget | 6000 tokens | Total token budget for LLM context |
| Blocked Keywords | — | Comma-separated PII keywords (names, address) |

### Step 4: Action Policy

| Field | Default | Description |
|-------|---------|-------------|
| Allowed Domains | `*` (all) | Domains the agent can control directly |
| Restricted Domains | `lock, camera` | Domains requiring Telegram confirmation |
| Blocked Domains | `homeassistant` | Domains NEVER callable |
| Confirmation Services | `lock.unlock, lock.lock, camera.turn_on, ...` | Specific services needing confirmation |

### Step 5: InfluxDB (Optional)

| Field | Default | Description |
|-------|---------|-------------|
| InfluxDB URL | `http://influx.internal` | InfluxDB v2 server URL |
| Token | — | InfluxDB authentication token |
| Organization | — | InfluxDB org |
| Bucket | — | InfluxDB bucket with HA data |

Leave empty to skip event-driven learning.

## Options Flow

After initial setup, all settings can be reconfigured via:
Settings → Devices & Services → Personal Assistant → Configure

## Ollama Setup

1. Install Ollama: `curl -fsSL https://ollama.ai/install.sh | sh`
2. Pull models:
   ```bash
   ollama pull gpt-oss:20b
   ollama pull nomic-embed-text
   ```
3. Ensure Ollama is accessible from HA (check firewall, use `0.0.0.0` binding)
4. For larger context windows, configure `num_ctx` in model options

## Context Budget Tuning

Default budget is optimized for 8K context. If you increase Ollama's `num_ctx`:

| num_ctx | Recommended Budget |
|---------|-------------------|
| 8K | 6000 (default) |
| 16K | 12000 |
| 32K | 24000 |
| 128K | 96000 |

Set via config flow Step 3 or options flow.

## HA Services

The integration registers these services:

| Service | Description |
|---------|-------------|
| `ha_personal_assistant.reindex` | Trigger immediate RAG re-index |
| `ha_personal_assistant.clear_profile` | Clear profile entries (optional category filter) |
| `ha_personal_assistant.clear_conversation_history` | Clear conversation history (optional chat_id filter) |

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/searchlog` | View recent web search audit log |
