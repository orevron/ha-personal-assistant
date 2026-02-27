# Security

## Threat Model

| Vector | Risk | Data at Risk | Severity |
|--------|------|-------------|----------|
| Web search queries | Agent includes PII in search terms | Names, addresses, routines, entity IDs | 🔴 Critical |
| Cloud LLM requests | Full conversation sent to OpenAI/Gemini | All conversation content, profile, HA state | 🔴 Critical |
| Agent reasoning | LLM combines profile with search | Sleep schedule, location patterns | 🟠 High |
| Error messages | Stack traces leak config/tokens | API tokens, internal IPs | 🟡 Medium |
| SQLite at rest | Unencrypted local storage | Profile, habits, conversation history | 🟡 Medium |
| Prompt injection | Malicious web/RAG content | Agent tricked into unintended actions | 🔴 Critical |
| Uncontrolled HA actions | Hallucinated service calls | Locks, alarms, covers | 🔴 Critical |

## Mitigation Controls

### M1 — PII Sanitizer (`tools/sanitizer.py`)

Mandatory pre-filter on all web search queries. Detects and removes:
- Phone numbers, email addresses, IP addresses
- HA entity IDs (e.g., `light.bedroom_lamp`)
- MAC addresses, GPS coordinates, street addresses
- Schedule/routine details
- User-configured blocked keywords (names, address parts)

Queries with excessive PII are blocked entirely. All queries logged to `search_audit_log`.

### M2 — Search Query Audit Log

Every web search is logged before execution in `search_audit_log` table. Users can review via `/searchlog` Telegram command.

### M3 — System Prompt Security Rules (`agent/prompts.py`)

Hard-coded, non-overridable rules injected into every agent invocation. Includes search recovery protocol for blocked queries.

### M4 — Cloud LLM Data Policy (`agent/router.py`)

- Default: local Ollama only (cloud is opt-in)
- `cloud_llm_send_profile` / `cloud_llm_send_ha_state` flags strip context for cloud
- Cloud LLM gets stripped-down system prompt without sensitive data

### M5 — Sensitive Data Classification

Profile entries tagged with sensitivity: `public` | `private` | `sensitive`

| Level | Allowed in... |
|-------|--------------|
| `public` | All contexts |
| `private` | Local LLM only |
| `sensitive` | Local LLM only, never cloud/web |

### M7 — Action Permission Layer (`tools/action_policy.py`)

Three-tier policy for HA service calls:
- **Allowed**: Direct execution (default for most domains)
- **Restricted**: Requires Telegram confirmation (lock, camera)
- **Blocked**: Never callable (homeassistant domain)

Uses LangGraph `interrupt()` for confirmation flow with inline keyboard.

### M8 — Content Firewall (`tools/content_firewall.py`)

Strips prompt injection from web results and RAG content:
- Instruction overrides ("ignore previous instructions")
- Persona hijacking ("you are now...")
- Embedded commands ("execute command", "call service")
- Tool call injection (JSON function patterns)

### M9 — Context Budget Control (`agent/context_assembler.py`)

Token budget prevents context explosion. Default for 8K context:

| Slot | Tokens |
|------|--------|
| System prompt | ~800 |
| User profile | ~400 |
| HA context | ~800 |
| Conversation history | ~2000 |
| RAG results | ~800 |
| Tool overhead | ~1200 |
| **Total** | **~6000** |

Auto-scales proportionally if Ollama `num_ctx` is increased.
