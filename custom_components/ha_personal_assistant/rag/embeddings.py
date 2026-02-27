"""Embedding pipeline using Ollama's nomic-embed-text model."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)


class OllamaEmbeddings:
    """Generate embeddings using Ollama's embedding API.

    Uses the nomic-embed-text model by default for generating
    768-dimensional embeddings for RAG retrieval.
    """

    def __init__(self, base_url: str, model: str = "nomic-embed-text") -> None:
        """Initialize the embeddings provider.

        Args:
            base_url: Ollama server URL.
            model: Embedding model name.
        """
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._dimension: int | None = None

    @property
    def dimension(self) -> int:
        """Return the embedding dimension (default 768 for nomic-embed-text)."""
        return self._dimension or 768

    async def aembed_text(self, text: str) -> list[float]:
        """Generate an embedding for a single text.

        Args:
            text: Text to embed.

        Returns:
            List of floats representing the embedding vector.
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._base_url}/api/embed",
                    json={"model": self._model, "input": text},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        _LOGGER.error("Ollama embed error (%d): %s", resp.status, error_text)
                        return []

                    data = await resp.json()
                    embeddings = data.get("embeddings", [])
                    if embeddings:
                        embedding = embeddings[0]
                        if self._dimension is None:
                            self._dimension = len(embedding)
                        return embedding

                    return []
        except Exception as err:
            _LOGGER.error("Error generating embedding: %s", err)
            return []

    async def aembed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.
        """
        results = []
        for text in texts:
            embedding = await self.aembed_text(text)
            results.append(embedding)
        return results

    async def ahealth_check(self) -> bool:
        """Check if the embedding model is available."""
        try:
            result = await self.aembed_text("test")
            return len(result) > 0
        except Exception:
            return False
