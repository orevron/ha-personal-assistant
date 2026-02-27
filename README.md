# Home Assistant Personal Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/v/release/YOUR_USER/ha-personal-assistant)](https://github.com/YOUR_USER/ha-personal-assistant/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Home Assistant custom integration for an intelligent personal assistant that communicates via Telegram, controls your smart home with natural language, searches the web, and learns your preferences over time — all running locally on [Ollama](https://ollama.ai/).

## Features

- 💬 **Telegram Interface** — chat with your assistant through Home Assistant's built-in Telegram integration
- 🏠 **Smart Home Control** — query entity states and call services using natural language
- 🔒 **Action Permission Layer** — three-tier security for service calls (allowed / confirmation required / blocked)
- 🌐 **Web Search** — DuckDuckGo search with automatic PII sanitization and prompt injection firewall
- 🧠 **RAG Knowledge Base** — retrieval-augmented generation over your entities, automations, and scenes using [sqlite-vec](https://github.com/asg017/sqlite-vec)
- 📝 **User Profile Learning** — remembers your preferences, habits, and routines across sessions
- 📊 **Event-Driven Learning** — detects behavioral patterns from InfluxDB historical data
- 🔐 **Privacy First** — 9 security controls (M1–M9) protect against data leaks and prompt injection
- 🖥️ **Local-First** — runs entirely on local Ollama LLM, with optional OpenAI / Gemini fallback

## Prerequisites

| Requirement | Details |
|---|---|
| Home Assistant | 2024.1 or later |
| [Telegram Bot](https://www.home-assistant.io/integrations/telegram_bot/) | HA Telegram integration configured with bot token and allowed chat IDs |
| [Ollama](https://ollama.ai/) | Running and accessible from HA, with models pulled (see below) |
| InfluxDB *(optional)* | For event-driven behavior learning |
| Cloud LLM API key *(optional)* | OpenAI or Google Gemini for cloud fallback |

**Pull the required Ollama models:**

```bash
ollama pull gpt-oss:20b
ollama pull nomic-embed-text
```

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots in the top right corner → **Custom repositories**
3. Add this repository URL and select **Integration** as category
4. Search for **Personal Assistant** and click **Download**
5. Restart Home Assistant

### Manual

1. Download the [latest release](https://github.com/YOUR_USER/ha-personal-assistant/releases/latest)
2. Copy the `custom_components/ha_personal_assistant` folder to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

Configuration > [Integrations](https://my.home-assistant.io/redirect/integrations/) > Add Integration > **Personal Assistant**

The setup wizard guides you through 5 steps:

| Step | What you configure |
|---|---|
| 1. Ollama | Server URL, chat model, embedding model |
| 2. Cloud LLM | *(Optional)* OpenAI or Gemini API key and model |
| 3. Persona | Agent personality, session timeout, context budget, PII keywords |
| 4. Action Policy | Allowed / restricted / blocked domains and confirmation services |
| 5. InfluxDB | *(Optional)* URL, token, org, bucket for event-driven learning |

To reconfigure after setup: Configuration > [Integrations](https://my.home-assistant.io/redirect/integrations/) > **Personal Assistant** > Configure

For detailed configuration reference, see [docs/configuration.md](custom_components/ha_personal_assistant/docs/configuration.md).

## Usage

Send a message to your Telegram bot:

| Example | What happens |
|---|---|
| *"What lights are on?"* | Agent queries HA entities and lists active lights |
| *"Turn off the kitchen light"* | Agent finds the entity and calls `light.turn_off` |
| *"Unlock the front door"* | Agent requests confirmation via inline keyboard (restricted domain) |
| *"What automations do I have for the bedroom?"* | RAG retrieval over indexed automations |
| *"I prefer 22 degrees"* | Stores preference in user profile for future reference |
| *"What's the weather in Tel Aviv?"* | PII-sanitized DuckDuckGo search |

### Telegram Commands

| Command | Description |
|---|---|
| `/searchlog` | View recent web search audit log |

### HA Services

| Service | Description |
|---|---|
| `ha_personal_assistant.reindex` | Trigger immediate RAG re-index |
| `ha_personal_assistant.clear_profile` | Clear learned profile entries |
| `ha_personal_assistant.clear_conversation_history` | Clear conversation history |

### Entities

| Entity | Description |
|---|---|
| `button.ha_personal_assistant_sync_now` | Button to trigger immediate RAG re-index from any dashboard |

## Security

This integration implements 9 security controls to prevent data leaks and prompt injection:

| Control | Purpose |
|---|---|
| **M1** — PII Sanitizer | Strips personal data from web search queries |
| **M2** — Search Audit Log | Logs every search query for review |
| **M3** — System Prompt Rules | Hard-coded security instructions in every LLM call |
| **M4** — Cloud LLM Data Policy | Strips sensitive context when using cloud providers |
| **M5** — Data Classification | Tags profile data as public / private / sensitive |
| **M7** — Action Permission Layer | Three-tier policy for HA service calls |
| **M8** — Content Firewall | Filters prompt injection from web results and RAG content |
| **M9** — Context Budget | Prevents token budget overflow |

For the full threat model and control details, see [docs/security.md](custom_components/ha_personal_assistant/docs/security.md).

## Architecture

```
User → Telegram → HA Telegram Integration → Event Bus
                                                 ↓
                                    ha_personal_assistant
                                                 ↓
                                       Context Assembler (M9)
                                                 ↓
                                       LangGraph ReAct Agent
                                            ↙    ↓    ↘
                                     HA Tools   Search   RAG
                                        ↓         ↓       ↓
                                  Policy (M7)  PII (M1)  Firewall (M8)
                                                 ↓
                                       Background Learner
                                                 ↓
                                         Profile Manager
```

For the full architecture deep-dive, see [docs/architecture.md](custom_components/ha_personal_assistant/docs/architecture.md).

## Documentation

| Document | Description |
|---|---|
| [Architecture](custom_components/ha_personal_assistant/docs/architecture.md) | System architecture, data flow, async execution model |
| [Security](custom_components/ha_personal_assistant/docs/security.md) | Threat model, all M1–M9 controls, data classification |
| [Tools Reference](custom_components/ha_personal_assistant/docs/tools.md) | Agent tools, inputs/outputs, permission layer, interrupt flow |
| [RAG & Memory](custom_components/ha_personal_assistant/docs/rag_and_memory.md) | RAG engine, sqlite-vec, profile system, learning pipeline |
| [Configuration](custom_components/ha_personal_assistant/docs/configuration.md) | Config flow walkthrough, Ollama setup, action policies |
| [Troubleshooting](custom_components/ha_personal_assistant/docs/troubleshooting.md) | Common issues, debugging, log analysis |

## Debugging

Enable debug logging in `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.ha_personal_assistant: debug
```

## Issues

Before opening a new issue:

1. Check the [Troubleshooting guide](custom_components/ha_personal_assistant/docs/troubleshooting.md)
2. Check [Logs](https://my.home-assistant.io/redirect/logs/) for errors (filter `ha_personal_assistant`)
3. Check open and closed [issues](https://github.com/YOUR_USER/ha-personal-assistant/issues?q=is%3Aissue)

When reporting an issue, please include:
- Home Assistant version
- Integration version
- Relevant log entries (with debug logging enabled)
- Steps to reproduce

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

[MIT](LICENSE)
