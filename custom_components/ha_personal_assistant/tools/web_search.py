"""Web Search tool — DuckDuckGo search with PII sanitizer and content firewall."""
from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langchain_core.tools import tool
from sqlalchemy.orm import sessionmaker

_LOGGER = logging.getLogger(__name__)


def create_web_search_tools(
    pii_sanitizer: Any,
    content_firewall: Any,
    engine: Any,
    executor: ThreadPoolExecutor,
) -> list:
    """Create LangChain tools for web search with security controls.

    Args:
        pii_sanitizer: PIISanitizer instance (M1).
        content_firewall: ContentFirewall instance (M8).
        engine: SQLAlchemy engine for audit logging.
        executor: ThreadPoolExecutor for sync operations.

    Returns:
        List of LangChain tools.
    """
    Session = sessionmaker(bind=engine)

    @tool
    async def search_web(query: str) -> str:
        """Search the internet for information using DuckDuckGo.

        All queries are automatically sanitized to prevent personal data leaks.
        If the query contains personal information, it will be blocked.
        In that case, reformulate with generic terms.

        IMPORTANT: NEVER include personal information, entity IDs, IP addresses,
        names, addresses, or schedule details in search queries.

        Args:
            query: The search query. Must be generic and not contain personal data.

        Returns:
            JSON with search results (title, snippet, URL) or error message.
        """
        # Step 1: PII Sanitization (M1)
        sanitize_result = pii_sanitizer.sanitize_search_query(query)

        # Step 2: Audit log (always, even for blocked queries)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            executor,
            _log_search_audit,
            Session,
            query,
            sanitize_result.query if not sanitize_result.was_blocked else "",
            sanitize_result.was_blocked,
            sanitize_result.block_reason,
        )

        # Step 3: Handle blocked queries
        if sanitize_result.was_blocked:
            _LOGGER.warning(
                "Web search BLOCKED by PII sanitizer: %s (reason: %s)",
                query[:80], sanitize_result.block_reason,
            )
            return json.dumps({
                "status": "blocked",
                "reason": sanitize_result.block_reason,
                "suggestion": (
                    "The query contained personal data and was blocked for privacy. "
                    "Please reformulate using GENERIC terms. For example:\n"
                    "- Instead of specific entity IDs, use device types\n"
                    "- Instead of names/locations, use generic descriptions\n"
                    "- Instead of schedules, ask general questions"
                ),
            })

        if sanitize_result.was_modified:
            _LOGGER.info(
                "Search query sanitized: '%s' -> '%s' (removed: %s)",
                query[:50], sanitize_result.query[:50], sanitize_result.removed_items,
            )

        sanitized_query = sanitize_result.query

        # Step 4: Execute search
        try:
            results = await loop.run_in_executor(
                executor,
                _execute_search_sync,
                sanitized_query,
            )

            if not results:
                return json.dumps({
                    "status": "no_results",
                    "query": sanitized_query,
                    "message": "No results found for the query.",
                })

            # Step 5: Content Firewall (M8) — filter results
            filtered_results = []
            for result in results:
                title = content_firewall.sanitize_content(result.get("title", ""))
                snippet = content_firewall.sanitize_content(result.get("body", result.get("snippet", "")))

                if title or snippet:  # Only include if content remains after filtering
                    filtered_results.append({
                        "title": title,
                        "snippet": snippet,
                        "url": result.get("href", result.get("url", "")),
                    })

            return json.dumps({
                "status": "success",
                "query": sanitized_query,
                "results": filtered_results[:5],  # Top 5
            }, indent=2)

        except Exception as err:
            _LOGGER.error("Web search error: %s", err)
            return json.dumps({
                "status": "error",
                "error": str(err),
                "message": "Web search failed. Try answering from your knowledge instead.",
            })

    return [search_web]


def _execute_search_sync(query: str) -> list[dict[str, Any]]:
    """Execute a DuckDuckGo search synchronously.

    Args:
        query: Sanitized search query.

    Returns:
        List of result dicts.
    """
    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
            return results
    except Exception as err:
        _LOGGER.error("DuckDuckGo search error: %s", err)
        return []


def _log_search_audit(
    Session: Any,
    original_query: str,
    sanitized_query: str,
    was_blocked: bool,
    block_reason: str,
    session_id: str = "",
) -> None:
    """Log search query to audit table.

    Args:
        Session: SQLAlchemy session factory.
        original_query: The original query from the agent.
        sanitized_query: The sanitized query (empty if blocked).
        was_blocked: Whether the query was blocked.
        block_reason: Reason for blocking (if blocked).
        session_id: Optional session ID.
    """
    from ..memory.models import SearchAuditLog

    try:
        db_session = Session()
        try:
            log = SearchAuditLog(
                session_id=session_id,
                original_query=original_query,
                sanitized_query=sanitized_query or "",
                was_blocked=was_blocked,
                block_reason=block_reason,
            )
            db_session.add(log)
            db_session.commit()
        finally:
            db_session.close()
    except Exception as err:
        _LOGGER.error("Failed to log search audit: %s", err)


async def get_recent_search_log(
    engine: Any,
    executor: ThreadPoolExecutor,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Get recent search log entries for the /searchlog command.

    Args:
        engine: SQLAlchemy engine.
        executor: ThreadPoolExecutor.
        limit: Max entries to return.

    Returns:
        List of search log entry dicts.
    """
    Session = sessionmaker(bind=engine)

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        executor, _get_recent_log_sync, Session, limit
    )


def _get_recent_log_sync(Session: Any, limit: int) -> list[dict[str, Any]]:
    """Synchronous search log retrieval."""
    from ..memory.models import SearchAuditLog

    db_session = Session()
    try:
        entries = (
            db_session.query(SearchAuditLog)
            .order_by(SearchAuditLog.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "original_query": e.original_query,
                "sanitized_query": e.sanitized_query,
                "was_blocked": e.was_blocked,
                "block_reason": e.block_reason,
                "timestamp": str(e.timestamp) if e.timestamp else None,
            }
            for e in entries
        ]
    finally:
        db_session.close()
