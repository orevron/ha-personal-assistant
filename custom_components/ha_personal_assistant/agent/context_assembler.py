"""Context Assembler (M9) — Token budget controller for LLM context.

Assembles a budget-controlled context from multiple sources:
  - System prompt + security rules
  - User profile subset
  - HA entity context
  - Conversation history (summarized if needed)
  - RAG results
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Rough estimation: 1 token ≈ 4 characters (for English text)
CHARS_PER_TOKEN = 4


@dataclass
class ContextBudget:
    """Token budget allocation for each context slot."""
    system_prompt: int = 800
    user_profile: int = 400
    ha_context: int = 800
    conversation_history: int = 2000
    rag_results: int = 800
    tool_overhead: int = 1200
    total: int = 6000

    @classmethod
    def from_total(cls, total: int) -> ContextBudget:
        """Create a proportional budget from a total token count.

        Scales all slots proportionally to the total.
        """
        base_total = 6000
        ratio = total / base_total
        return cls(
            system_prompt=int(800 * ratio),
            user_profile=int(400 * ratio),
            ha_context=int(800 * ratio),
            conversation_history=int(2000 * ratio),
            rag_results=int(800 * ratio),
            tool_overhead=int(1200 * ratio),
            total=total,
        )


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in a text string."""
    return len(text) // CHARS_PER_TOKEN


def truncate_to_budget(text: str, max_tokens: int) -> str:
    """Truncate text to fit within a token budget.

    Truncates at the last complete line that fits within the budget.
    """
    max_chars = max_tokens * CHARS_PER_TOKEN
    if len(text) <= max_chars:
        return text

    # Find the last newline within budget
    truncated = text[:max_chars]
    last_newline = truncated.rfind("\n")
    if last_newline > 0:
        truncated = truncated[:last_newline]

    return truncated + "\n... (truncated to fit context budget)"


class ContextAssembler:
    """Assembles budget-controlled context for LLM calls.

    Runs before every LLM invocation to ensure context stays within model limits.
    """

    def __init__(self, budget: ContextBudget | None = None) -> None:
        """Initialize with a token budget."""
        self._budget = budget or ContextBudget()

    @property
    def budget(self) -> ContextBudget:
        """Return the current budget."""
        return self._budget

    def assemble_profile_context(
        self,
        profile_entries: list[dict[str, Any]],
        query: str = "",
    ) -> str:
        """Select and format relevant profile entries within budget.

        If a query is provided, prioritize entries that are semantically
        relevant to the query (keyword matching as a heuristic).

        Args:
            profile_entries: List of profile entry dicts.
            query: User's current message (for relevance filtering).

        Returns:
            Formatted profile string within token budget.
        """
        if not profile_entries:
            return ""

        # Score entries by relevance to query
        scored = []
        query_words = set(query.lower().split()) if query else set()

        for entry in profile_entries:
            score = 0
            entry_text = f"{entry.get('category', '')} {entry.get('key', '')} {entry.get('value', '')}".lower()

            if query_words:
                # Count word overlaps for relevance
                entry_words = set(entry_text.split())
                overlap = query_words & entry_words
                score = len(overlap)

            # High-confidence entries get a boost
            confidence = entry.get("confidence", 0.5)
            score += confidence

            scored.append((score, entry))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Build formatted profile within budget
        lines = []
        token_count = 0

        for _score, entry in scored:
            line = f"- {entry['category']}/{entry['key']}: {entry['value']} (confidence: {entry.get('confidence', 0.5):.1f})"
            line_tokens = estimate_tokens(line)
            if token_count + line_tokens > self._budget.user_profile:
                break
            lines.append(line)
            token_count += line_tokens

        return "\n".join(lines)

    def assemble_ha_context(
        self,
        entities: list[dict[str, Any]],
        query: str = "",
    ) -> str:
        """Select and format relevant HA entity states within budget.

        Filters entities based on keyword/area matching with the query.

        Args:
            entities: List of entity state dicts.
            query: User's current message (for relevance filtering).

        Returns:
            Formatted HA context string within token budget.
        """
        if not entities:
            return ""

        # Score entities by relevance
        scored = []
        query_lower = query.lower() if query else ""
        query_words = set(query_lower.split()) if query else set()

        for entity in entities:
            score = 0
            entity_id = entity.get("entity_id", "")
            friendly_name = entity.get("friendly_name", "").lower()
            area = entity.get("area", "").lower()
            domain = entity_id.split(".")[0] if "." in entity_id else ""

            if query_words:
                # Check if query mentions this entity's name, area, or domain
                entity_words = set(f"{friendly_name} {area} {domain}".split())
                overlap = query_words & entity_words
                score = len(overlap) * 2

                # Bonus for exact substring matches
                if any(w in friendly_name for w in query_words):
                    score += 3
                if any(w in area for w in query_words):
                    score += 2

            scored.append((score, entity))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Build formatted context
        lines = []
        token_count = 0

        for _score, entity in scored:
            entity_id = entity.get("entity_id", "unknown")
            state = entity.get("state", "unknown")
            friendly_name = entity.get("friendly_name", entity_id)
            line = f"- {friendly_name} ({entity_id}): {state}"
            line_tokens = estimate_tokens(line)
            if token_count + line_tokens > self._budget.ha_context:
                break
            lines.append(line)
            token_count += line_tokens

        return "\n".join(lines)

    async def summarize_conversation(
        self,
        messages: list[dict[str, str]],
        llm: Any = None,
    ) -> str:
        """Summarize conversation history if it exceeds budget.

        Keeps recent messages verbatim and summarizes older ones.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            llm: Optional LLM instance for generating summaries.

        Returns:
            Formatted conversation history within token budget.
        """
        if not messages:
            return ""

        # Format all messages
        formatted_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            formatted_messages.append(f"{role}: {content}")

        full_history = "\n".join(formatted_messages)
        total_tokens = estimate_tokens(full_history)

        # If within budget, return as-is
        if total_tokens <= self._budget.conversation_history:
            return full_history

        # Keep recent messages verbatim (last 4 turns)
        recent_count = min(4, len(formatted_messages))
        recent = formatted_messages[-recent_count:]
        older = formatted_messages[:-recent_count]

        recent_text = "\n".join(recent)
        recent_tokens = estimate_tokens(recent_text)

        # Budget remaining for summary
        summary_budget = self._budget.conversation_history - recent_tokens

        if summary_budget <= 0:
            # Even recent messages exceed budget — truncate
            return truncate_to_budget(recent_text, self._budget.conversation_history)

        if older and llm:
            try:
                # Use LLM to summarize older messages
                older_text = "\n".join(older)
                summary_prompt = (
                    "Summarize the following conversation concisely, preserving key facts, "
                    "decisions, and preferences mentioned:\n\n"
                    f"{older_text}\n\n"
                    "Summary (be brief):"
                )
                response = await llm.ainvoke(summary_prompt)
                summary = response.content if hasattr(response, "content") else str(response)
                summary = truncate_to_budget(summary, summary_budget)
                return f"[Earlier conversation summary]: {summary}\n\n{recent_text}"
            except Exception as err:
                _LOGGER.warning("Failed to summarize conversation: %s", err)

        # Fallback: truncate older messages
        if older:
            older_text = "\n".join(older)
            older_truncated = truncate_to_budget(older_text, summary_budget)
            return f"{older_truncated}\n\n{recent_text}"

        return recent_text

    def assemble_rag_context(self, rag_results: list[dict[str, Any]]) -> str:
        """Format RAG results within the remaining budget.

        Args:
            rag_results: List of RAG result dicts with 'content' and 'metadata'.

        Returns:
            Formatted RAG context string.
        """
        if not rag_results:
            return ""

        lines = []
        token_count = 0

        for result in rag_results:
            content = result.get("content", "")
            source = result.get("metadata", {}).get("source", "unknown")
            line = f"[{source}]: {content}"
            line_tokens = estimate_tokens(line)
            if token_count + line_tokens > self._budget.rag_results:
                break
            lines.append(line)
            token_count += line_tokens

        return "\n".join(lines)
