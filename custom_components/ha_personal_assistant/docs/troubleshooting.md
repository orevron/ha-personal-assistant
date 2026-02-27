# Troubleshooting

## Common Issues

### Ollama Unreachable

**Symptoms:** Config flow shows "Cannot connect to Ollama server", or agent returns errors.

**Fixes:**
1. Verify Ollama is running: `curl http://192.168.1.97:11434/api/tags`
2. Check Ollama is bound to `0.0.0.0` (not just localhost)
3. Check firewall rules between HA and Ollama server
4. Verify models are pulled:
   ```bash
   ollama list  # Should show gpt-oss:20b and nomic-embed-text
   ```

### Telegram Events Not Firing

**Symptoms:** Messages sent to bot but no response from the assistant.

**Fixes:**
1. Verify HA Telegram Bot integration is configured and running
2. Check your chat ID is in the `allowed_chat_ids` list
3. Check HA logs for `telegram_text` events:
   ```
   Settings → System → Logs → filter "telegram"
   ```
4. Test with: Developer Tools → Events → Listen to `telegram_text`
5. Ensure bot is not blocked or deactivated in Telegram

### Entity ID Mismatches

**Symptoms:** Agent says "Entity not found" or controls wrong device.

**Fixes:**
1. The agent should always use `get_ha_entities` first — check logs for this
2. Entity IDs may have changed after HA restart — trigger a RAG reindex:
   - Press the "Sync Now" button in HA dashboard
   - Or call service `ha_personal_assistant.reindex`
3. Check if entity is in the correct area (area registry)

### RAG Returning Stale Data

**Symptoms:** Agent refers to outdated entity states or missing automations.

**Fixes:**
1. Trigger manual reindex via `button.ha_personal_assistant_sync_now`
2. Check last reindex time in logs (search for "RAG re-index")
3. Verify Ollama embedding model is responding:
   ```bash
   curl http://192.168.1.97:11434/api/embed -d '{"model":"nomic-embed-text","input":"test"}'
   ```
4. Check sqlite-vec extension is loaded (look for errors in logs)

### Token Budget Overflow

**Symptoms:** Agent responses are cut off, context seems incomplete, or Ollama is very slow.

**Fixes:**
1. Check context budget in config (default: 6000 tokens for 8K context)
2. If using a model with larger context, increase the budget proportionally
3. Reduce the number of entity states by being more specific in queries
4. Clear old conversation history: `ha_personal_assistant.clear_conversation_history`

### Blocked Searches

**Symptoms:** Agent says "Search was blocked by PII sanitizer."

**Fixes:**
1. This is expected behavior — the sanitizer is protecting your privacy
2. Rephrase with generic terms (no entity IDs, names, or addresses)
3. Check `/searchlog` to see what was blocked and why
4. Review blocked_keywords in config if too aggressive

### Action Confirmation Not Working

**Symptoms:** Restricted actions (lock/camera) don't show confirmation keyboard.

**Fixes:**
1. Check that `telegram_callback` events are being received by HA
2. Ensure the Telegram bot has inline keyboard permissions
3. Check LangGraph checkpointer DB exists at `ha_personal_assistant/langgraph_checkpoints.db`
4. If graph state is corrupted, delete the checkpointer DB and restart

### Learning Worker Not Updating Profile

**Symptoms:** Assistant doesn't remember stated preferences.

**Fixes:**
1. Check logs for "Learning worker" messages
2. Verify the worker is running (should log "Learning worker started" on startup)
3. Profile updates require the local LLM — cloud LLM can't be used for learning
4. Check profile entries: use `get_user_profile` tool or check the DB directly

## Debug Mode

Enable detailed logging in `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.ha_personal_assistant: debug
```

This will show:
- All incoming Telegram messages
- Agent tool calls and responses
- PII sanitizer decisions
- Content firewall blocks
- RAG retrieval results
- Profile updates
- Learning worker activity

## Log Analysis

Key log prefixes to filter:
- `ha_personal_assistant` — general integration logs
- `Action BLOCKED` / `Action NEEDS CONFIRMATION` — policy decisions
- `Content Firewall` — injection detection
- `Search query sanitized` / `Web search BLOCKED` — PII sanitizer
- `RAG re-index` — indexing status
- `Learning worker` — background learning
- `Event learner` — InfluxDB pattern detection

## Database Inspection

The SQLite database can be inspected directly:

```bash
sqlite3 /config/ha_personal_assistant/assistant.db

# View profile entries
SELECT * FROM profile_entries ORDER BY confidence DESC;

# View search audit log
SELECT * FROM search_audit_log ORDER BY timestamp DESC LIMIT 10;

# View conversation history
SELECT * FROM conversation_history ORDER BY timestamp DESC LIMIT 20;

# Check RAG document count
SELECT source_type, COUNT(*) FROM rag_documents GROUP BY source_type;
```
