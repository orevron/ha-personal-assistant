"""PII Sanitizer (M1) — mandatory pre-filter for all outbound queries.

Strips personal/sensitive data from web search queries before they leave
the system. This is the first line of defense against data leaks.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

_LOGGER = logging.getLogger(__name__)


@dataclass
class SanitizeResult:
    """Result of a sanitization check."""
    query: str
    was_modified: bool
    was_blocked: bool
    block_reason: str = ""
    removed_items: list[str] = field(default_factory=list)


class PIISanitizer:
    """Strips personal/sensitive data from outbound queries.

    Rules enforced:
    - NEVER include real names, addresses, phone numbers in searches
    - NEVER include HA entity IDs (e.g., light.bedroom_lamp)
    - NEVER include IP addresses or network info
    - NEVER include routine/schedule details
    - NEVER include location-identifying info
    - Generic queries only
    """

    # Regex patterns for personal identifiers
    BLOCKED_PATTERNS = [
        # Phone numbers (various formats)
        (r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', "phone number"),
        (r'\b\+\d{1,3}[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}\b', "phone number"),
        # Email addresses
        (r'\b[\w.+-]+@[\w-]+\.[\w.]+\b', "email address"),
        # IP addresses (IPv4)
        (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', "IP address"),
        # IP addresses (IPv6)
        (r'\b[0-9a-fA-F]{1,4}(:[0-9a-fA-F]{1,4}){7}\b', "IPv6 address"),
        # HA entity IDs (domain.name_pattern)
        (r'\b[a-z_]+\.[a-z][a-z0-9_]+\b', "entity ID"),
        # MAC addresses
        (r'\b([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b', "MAC address"),
        # GPS coordinates
        (r'\b-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}\b', "GPS coordinates"),
        # Street addresses (basic pattern)
        (r'\b\d+\s+[A-Z][a-zA-Z]+\s+(street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr)\b', "street address"),
    ]

    # Patterns indicating time/schedule information
    SCHEDULE_PATTERNS = [
        (r'\b(wakes?\s+(?:up\s+)?at|gets?\s+up\s+at|goes?\s+to\s+(?:bed|sleep)\s+at)\s+\d{1,2}[:.]\d{2}\b', "schedule detail"),
        (r'\b(every\s+(?:day|night|morning|evening)\s+at)\s+\d{1,2}[:.]\d{2}\b', "routine detail"),
        (r'\buser\s+(?:wakes?|sleeps?|arrives?|leaves?|works?)\b', "user routine"),
    ]

    def __init__(self, blocked_keywords: list[str] | None = None) -> None:
        """Initialize the PII sanitizer.

        Args:
            blocked_keywords: User-configured blocked keywords (names, address parts, etc.)
        """
        self._blocked_keywords = [kw.lower() for kw in (blocked_keywords or [])]

    def sanitize_search_query(self, query: str) -> SanitizeResult:
        """Sanitize a search query by removing PII and sensitive data.

        Args:
            query: The raw search query from the agent.

        Returns:
            SanitizeResult with the sanitized query and metadata.
        """
        original = query
        was_modified = False
        removed_items = []

        # 1. Check regex patterns
        for pattern, label in self.BLOCKED_PATTERNS:
            matches = re.findall(pattern, query, re.IGNORECASE)
            if matches:
                query = re.sub(pattern, "[REMOVED]", query, flags=re.IGNORECASE)
                removed_items.append(f"{label}: {matches}")
                was_modified = True

        # 2. Check schedule patterns
        for pattern, label in self.SCHEDULE_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                query = re.sub(pattern, "[REMOVED]", query, flags=re.IGNORECASE)
                removed_items.append(label)
                was_modified = True

        # 3. Check blocked keywords
        for keyword in self._blocked_keywords:
            if keyword in query.lower():
                # Replace keyword preserving case
                pattern = re.compile(re.escape(keyword), re.IGNORECASE)
                query = pattern.sub("[REMOVED]", query)
                removed_items.append(f"blocked keyword: {keyword}")
                was_modified = True

        # 4. Check if the query is too heavily redacted (more removed than kept)
        if query.count("[REMOVED]") >= 2:
            _LOGGER.warning(
                "Search query blocked — too many PII items removed. Original: %s",
                original[:100],
            )
            return SanitizeResult(
                query="",
                was_modified=True,
                was_blocked=True,
                block_reason="Query contained too many personal data items",
                removed_items=removed_items,
            )

        # 5. Clean up the query
        query = re.sub(r'\[REMOVED\]\s*', '', query).strip()
        query = re.sub(r'\s+', ' ', query).strip()

        # 6. If query is now empty or too short, block it
        if len(query) < 3:
            return SanitizeResult(
                query="",
                was_modified=True,
                was_blocked=True,
                block_reason="Query too short after sanitization",
                removed_items=removed_items,
            )

        return SanitizeResult(
            query=query,
            was_modified=was_modified,
            was_blocked=False,
            removed_items=removed_items,
        )
