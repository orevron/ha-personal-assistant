# Home Assistant Personal Assistant

A custom Home Assistant integration that acts as an intelligent personal assistant. Communicates via Telegram, controls smart home devices, searches the web, learns your preferences, and uses retrieval-augmented generation (RAG) for accurate answers.

## Features

- **Telegram Interface** — Send/receive messages through HA's built-in Telegram integration
- **Smart Home Control** — Query and control HA entities with natural language
- **Action Permission Layer** — Three-tier security (allowed/restricted/blocked) for service calls
- **Web Search** — DuckDuckGo search with PII sanitization and content firewall
- **RAG Knowledge** — sqlite-vec powered retrieval over your entities, automations, and scenes
- **User Profile Learning** — Remembers preferences, habits, and patterns over time
- **Event-Driven Learning** — Observes HA state changes via InfluxDB to detect behavioral patterns
- **Local-First** — Runs on local Ollama LLM by default, with optional cloud fallback
- **Comprehensive Security** — PII sanitizer, content firewall, action policies, data classification

## Prerequisites

- Home Assistant (2024.1+)
- [Telegram Bot integration](https://www.home-assistant.io/integrations/telegram_bot/) configured in HA
- [Ollama](https://ollama.ai/) running locally with `gpt-oss:20b` and `nomic-embed-text` models
- (Optional) InfluxDB for event-driven learning
- (Optional) OpenAI or Google Gemini API key for cloud LLM fallback

## Quick Start

1. **Install Ollama models:**
   ```bash
   ollama pull gpt-oss:20b
   ollama pull nomic-embed-text
   ```

2. **Copy to custom_components:**
   ```bash
   cp -r custom_components/ha_personal_assistant /config/custom_components/
   ```

3. **Restart Home Assistant**

4. **Add Integration:**
   - Go to Settings → Devices & Services → Add Integration
   - Search for "Personal Assistant"
   - Follow the 5-step config flow (Ollama → Cloud LLM → Persona → Action Policy → InfluxDB)

5. **Send a Telegram message:**
   - Message your Telegram bot: "What lights are on?"

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](architecture.md) | System architecture, data flow, async model |
| [Security](security.md) | Threat model, M1-M9 controls, PII sanitizer |
| [Tools](tools.md) | Agent tools reference, permissions, interrupts |
| [RAG & Memory](rag_and_memory.md) | RAG engine, sqlite-vec, profile, learning |
| [Configuration](configuration.md) | Config flow, Ollama, policies, InfluxDB |
| [Troubleshooting](troubleshooting.md) | Common issues, debugging, log analysis |

## Architecture Overview

```
User → Telegram → HA Telegram Integration → Event Bus → Personal Assistant
                                                              ↓
                                                    Context Assembler (M9)
                                                              ↓
                                                    LangGraph ReAct Agent
                                                         ↙    ↓    ↘
                                                   HA Tools  Web Search  RAG
                                                     ↓         ↓          ↓
                                             Action Policy  PII Filter  Content Filter
                                                (M7)         (M1)        (M8)
                                                              ↓
                                                    Background Learner
                                                              ↓
                                                      Profile Manager
```

## License

MIT
