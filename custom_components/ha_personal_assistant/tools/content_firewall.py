"""Content Firewall (M8) — prompt injection filter for web/RAG results.

Strips suspected injection attempts from external content before it
reaches the agent. This prevents malicious web pages or RAG content
from hijacking the agent through prompt injection.
"""
from __future__ import annotations

import logging
import re

_LOGGER = logging.getLogger(__name__)


class ContentFirewall:
    """Filters prompt injection attempts from external content.

    Scans web search results and RAG retrieval content for patterns
    that look like prompt injection (e.g., "ignore previous instructions").
    Removes matching lines/paragraphs before passing to the agent.

    Blocked patterns include:
    - Instruction override attempts
    - Role/persona hijacking
    - Direct action commands embedded in content
    - Tool call / JSON function invocation attempts
    """

    # Patterns indicating prompt injection attempts
    INJECTION_PATTERNS = [
        # Instruction override
        (r'ignore\s+(previous|above|all|prior)\s+instructions?', "instruction override"),
        (r'disregard\s+(your|all|previous|prior)', "instruction override"),
        (r'forget\s+(everything|all|your)\s+(previous|above|prior)?', "instruction override"),
        # Role/persona hijacking
        (r'you\s+are\s+now\b', "persona hijacking"),
        (r'new\s+(instructions?|role|persona|identity)', "persona hijacking"),
        (r'act\s+as\s+(?:a\s+)?(?:different|new|evil)', "persona hijacking"),
        (r'pretend\s+(?:to\s+be|you\s+are)', "persona hijacking"),
        # System prompt manipulation
        (r'system\s*prompt', "system prompt access"),
        (r'reveal\s+(?:your|the)\s+(?:system|instructions|prompt)', "system prompt access"),
        (r'show\s+(?:me\s+)?(?:your|the)\s+(?:system|instructions|prompt)', "system prompt access"),
        # Direct action commands
        (r'\bexecute\b.*\b(command|service|action|function)\b', "embedded command"),
        (r'\bcall\s+(?:service|function|api)\b', "embedded command"),
        (r'\brun\s+(?:command|service|script)\b', "embedded command"),
        # HA-specific attacks
        (r'\b(?:unlock|disarm|open)\b.*\b(?:all|every|door|lock|alarm)\b', "HA action injection"),
        # JSON/tool call injection
        (r'\{\s*"(?:tool|function|action)"', "tool call injection"),
        (r'\{\s*"name"\s*:\s*"(?:call_ha_service|search_web)', "tool call injection"),
    ]

    # Severity levels for logging
    SEVERITY_HIGH = ["instruction override", "persona hijacking", "system prompt access", "HA action injection"]

    def sanitize_content(self, text: str) -> str:
        """Strip suspected injection attempts from external content.

        Processes the text line by line and paragraph by paragraph,
        removing any content that matches injection patterns.

        Args:
            text: Raw external content (web search result or RAG chunk).

        Returns:
            Sanitized text with injection attempts removed.
        """
        if not text:
            return text

        stripped_count = 0
        stripped_types = []

        # Process paragraph by paragraph
        paragraphs = text.split("\n\n")
        clean_paragraphs = []

        for paragraph in paragraphs:
            is_clean = True
            for pattern, pattern_type in self.INJECTION_PATTERNS:
                if re.search(pattern, paragraph, re.IGNORECASE):
                    is_clean = False
                    stripped_count += 1
                    if pattern_type not in stripped_types:
                        stripped_types.append(pattern_type)

                    severity = "HIGH" if pattern_type in self.SEVERITY_HIGH else "MEDIUM"
                    _LOGGER.warning(
                        "Content Firewall [%s]: Stripped '%s' injection from content (matched: %s...)",
                        severity,
                        pattern_type,
                        paragraph[:80],
                    )
                    break

            if is_clean:
                clean_paragraphs.append(paragraph)

        if stripped_count > 0:
            _LOGGER.info(
                "Content Firewall: Stripped %d suspicious paragraph(s) (%s)",
                stripped_count,
                ", ".join(stripped_types),
            )

        result = "\n\n".join(clean_paragraphs)

        # Second pass: line-by-line for remaining inline injection
        lines = result.split("\n")
        clean_lines = []
        for line in lines:
            line_clean = True
            for pattern, pattern_type in self.INJECTION_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    line_clean = False
                    _LOGGER.debug("Content Firewall: Stripped line — %s", line[:80])
                    break
            if line_clean:
                clean_lines.append(line)

        return "\n".join(clean_lines)

    def is_safe(self, text: str) -> bool:
        """Quick check if text contains any injection patterns.

        Args:
            text: Text to check.

        Returns:
            True if no injection patterns found.
        """
        for pattern, _ in self.INJECTION_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return False
        return True
