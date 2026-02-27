"""RAG tools — LangChain tools for RAG retrieval."""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import tool

_LOGGER = logging.getLogger(__name__)


def create_rag_tools(rag_engine: Any, content_firewall: Any) -> list:
    """Create LangChain tools for RAG retrieval.

    Args:
        rag_engine: RAGEngine instance.
        content_firewall: ContentFirewall instance for filtering results.

    Returns:
        List of LangChain tools.
    """

    @tool
    async def retrieve_knowledge(query: str, source_type: str = "") -> str:
        """Retrieve relevant knowledge from the indexed Home Assistant data.

        Searches through indexed entities, automations, scenes, history,
        and user profile data to find relevant information.

        Args:
            query: Natural language query to search for.
            source_type: Optional filter by source type ('entity', 'automation', 'scene', 'history', 'profile').

        Returns:
            JSON with relevant knowledge chunks.
        """
        try:
            results = await rag_engine.aretrieve(
                query=query,
                top_k=5,
                source_type=source_type if source_type else None,
            )

            if not results:
                return json.dumps({"results": [], "message": "No relevant knowledge found"})

            # Apply content firewall to RAG results
            filtered_results = []
            for result in results:
                content = result.get("content", "")
                sanitized = content_firewall.sanitize_content(content)
                if sanitized:  # Only include non-empty results
                    filtered_results.append({
                        "content": sanitized,
                        "source": result.get("source", "unknown"),
                        "source_type": result.get("source_type", "unknown"),
                        "relevance_distance": result.get("distance", 0),
                    })

            return json.dumps({"results": filtered_results}, indent=2)
        except Exception as err:
            _LOGGER.error("Error in RAG retrieval: %s", err)
            return json.dumps({"error": str(err)})

    return [retrieve_knowledge]
