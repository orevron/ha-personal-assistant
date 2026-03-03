"""RAG Engine — vector search with sqlite-vec (if available) or pure-Python fallback."""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import struct
from concurrent.futures import ThreadPoolExecutor
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Detect sqlite-vec availability at import time
_HAS_SQLITE_VEC = False
try:
    import sqlite_vec  # noqa: F401
    _HAS_SQLITE_VEC = True
except ImportError:
    _LOGGER.info("sqlite-vec not available; using pure-Python cosine similarity fallback")


def _serialize_embedding(embedding: list[float]) -> bytes:
    """Serialize a list of floats to bytes for sqlite-vec."""
    return struct.pack(f"{len(embedding)}f", *embedding)


def _deserialize_embedding(data: bytes, dim: int) -> list[float]:
    """Deserialize bytes back to a list of floats."""
    return list(struct.unpack(f"{dim}f", data))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class RAGEngine:
    """RAG engine using sqlite-vec for vector storage and retrieval.

    Uses a single SQLite database with the sqlite-vec extension for
    both vector storage and metadata. Supports cosine similarity search
    via KNN queries.

    Falls back to a pure-Python cosine similarity search when sqlite-vec
    is not available (e.g., in HAOS Docker environments).
    """

    def __init__(
        self,
        db_path: str,
        embeddings_provider: Any,
        executor: ThreadPoolExecutor,
    ) -> None:
        """Initialize the RAG engine.

        Args:
            db_path: Path to the SQLite database file.
            embeddings_provider: Embedding provider (OllamaEmbeddings).
            executor: ThreadPoolExecutor for sync DB operations.
        """
        self._db_path = db_path
        self._embeddings = embeddings_provider
        self._executor = executor
        self._conn: sqlite3.Connection | None = None
        self._use_vec: bool = False

    async def async_setup(self) -> None:
        """Initialize the sqlite-vec tables."""
        import asyncio

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, self._setup_sync)

    def _setup_sync(self) -> None:
        """Synchronous database setup."""
        self._conn = sqlite3.connect(self._db_path)

        # Try loading sqlite-vec extension
        if _HAS_SQLITE_VEC:
            try:
                self._conn.enable_load_extension(True)
                sqlite_vec.load(self._conn)
                self._conn.enable_load_extension(False)
                self._use_vec = True
                _LOGGER.info("sqlite-vec extension loaded successfully")
            except Exception as err:
                _LOGGER.warning("Failed to load sqlite-vec extension, using fallback: %s", err)
                self._use_vec = False

        cursor = self._conn.cursor()

        # Create metadata table for document chunks
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rag_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                source_type TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        dimension = self._embeddings.dimension

        if self._use_vec:
            # Use sqlite-vec virtual table for vector search
            cursor.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS rag_vectors
                USING vec0(
                    document_id INTEGER PRIMARY KEY,
                    embedding float[{dimension}]
                )
            """)
        else:
            # Fallback: store embeddings as BLOBs in a regular table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS rag_vectors (
                    document_id INTEGER PRIMARY KEY,
                    embedding BLOB NOT NULL
                )
            """)

        self._conn.commit()
        mode = "sqlite-vec" if self._use_vec else "pure-Python fallback"
        _LOGGER.info("RAG engine initialized with %s (dimension=%d)", mode, dimension)

    async def ainsert(
        self,
        content: str,
        source: str,
        source_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> int | None:
        """Insert a document chunk with its embedding.

        Args:
            content: Text content to index.
            source: Source identifier (e.g., entity_id, automation name).
            source_type: Type of source (e.g., 'entity', 'automation', 'profile').
            metadata: Optional metadata dict.

        Returns:
            Document ID or None on failure.
        """
        # Generate embedding
        embedding = await self._embeddings.aembed_text(content)
        if not embedding:
            _LOGGER.warning("Failed to generate embedding for: %s", content[:50])
            return None

        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self._insert_sync,
            content, source, source_type, metadata, embedding,
        )

    def _insert_sync(
        self,
        content: str,
        source: str,
        source_type: str,
        metadata: dict | None,
        embedding: list[float],
    ) -> int | None:
        """Synchronous insert."""
        if not self._conn:
            return None

        try:
            cursor = self._conn.cursor()

            # Insert document metadata
            cursor.execute(
                """INSERT INTO rag_documents (source, source_type, content, metadata)
                   VALUES (?, ?, ?, ?)""",
                (source, source_type, content, json.dumps(metadata or {})),
            )
            doc_id = cursor.lastrowid

            # Insert embedding vector
            cursor.execute(
                """INSERT INTO rag_vectors (document_id, embedding)
                   VALUES (?, ?)""",
                (doc_id, _serialize_embedding(embedding)),
            )

            self._conn.commit()
            return doc_id
        except Exception as err:
            _LOGGER.error("Error inserting document: %s", err)
            self._conn.rollback()
            return None

    async def aretrieve(
        self,
        query: str,
        top_k: int = 5,
        source_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve the most similar documents for a query.

        Args:
            query: Search query text.
            top_k: Number of results to return.
            source_type: Optional filter by source type.

        Returns:
            List of result dicts with 'content', 'source', 'metadata', 'distance'.
        """
        # Generate query embedding
        query_embedding = await self._embeddings.aembed_text(query)
        if not query_embedding:
            return []

        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self._retrieve_sync,
            query_embedding, top_k, source_type,
        )

    def _retrieve_sync(
        self,
        query_embedding: list[float],
        top_k: int,
        source_type: str | None,
    ) -> list[dict[str, Any]]:
        """Synchronous retrieval using KNN search or fallback."""
        if not self._conn:
            return []

        if self._use_vec:
            return self._retrieve_vec(query_embedding, top_k, source_type)
        else:
            return self._retrieve_fallback(query_embedding, top_k, source_type)

    def _retrieve_vec(
        self,
        query_embedding: list[float],
        top_k: int,
        source_type: str | None,
    ) -> list[dict[str, Any]]:
        """Retrieve using sqlite-vec KNN search."""
        try:
            cursor = self._conn.cursor()

            if source_type:
                cursor.execute(
                    """
                    SELECT d.id, d.source, d.source_type, d.content, d.metadata, v.distance
                    FROM rag_vectors v
                    JOIN rag_documents d ON d.id = v.document_id
                    WHERE v.embedding MATCH ?
                      AND k = ?
                      AND d.source_type = ?
                    ORDER BY v.distance
                    """,
                    (_serialize_embedding(query_embedding), top_k, source_type),
                )
            else:
                cursor.execute(
                    """
                    SELECT d.id, d.source, d.source_type, d.content, d.metadata, v.distance
                    FROM rag_vectors v
                    JOIN rag_documents d ON d.id = v.document_id
                    WHERE v.embedding MATCH ?
                      AND k = ?
                    ORDER BY v.distance
                    """,
                    (_serialize_embedding(query_embedding), top_k),
                )

            return self._parse_results(cursor.fetchall())
        except Exception as err:
            _LOGGER.error("Error during sqlite-vec retrieval: %s", err)
            return []

    def _retrieve_fallback(
        self,
        query_embedding: list[float],
        top_k: int,
        source_type: str | None,
    ) -> list[dict[str, Any]]:
        """Retrieve using pure-Python cosine similarity (fallback)."""
        try:
            cursor = self._conn.cursor()
            dim = self._embeddings.dimension

            if source_type:
                cursor.execute(
                    """
                    SELECT d.id, d.source, d.source_type, d.content, d.metadata, v.embedding
                    FROM rag_vectors v
                    JOIN rag_documents d ON d.id = v.document_id
                    WHERE d.source_type = ?
                    """,
                    (source_type,),
                )
            else:
                cursor.execute(
                    """
                    SELECT d.id, d.source, d.source_type, d.content, d.metadata, v.embedding
                    FROM rag_vectors v
                    JOIN rag_documents d ON d.id = v.document_id
                    """,
                )

            # Compute cosine similarity for each row
            scored = []
            for row in cursor.fetchall():
                stored_emb = _deserialize_embedding(row[5], dim)
                sim = _cosine_similarity(query_embedding, stored_emb)
                # Convert similarity to distance (lower = more similar)
                distance = 1.0 - sim
                scored.append((distance, row[:5]))

            # Sort by distance (ascending) and take top_k
            scored.sort(key=lambda x: x[0])
            top_results = scored[:top_k]

            results = []
            for distance, row in top_results:
                metadata = {}
                try:
                    metadata = json.loads(row[4]) if row[4] else {}
                except json.JSONDecodeError:
                    pass

                results.append({
                    "id": row[0],
                    "source": row[1],
                    "source_type": row[2],
                    "content": row[3],
                    "metadata": {**metadata, "source": row[1], "source_type": row[2]},
                    "distance": distance,
                })

            return results
        except Exception as err:
            _LOGGER.error("Error during fallback retrieval: %s", err)
            return []

    @staticmethod
    def _parse_results(rows: list) -> list[dict[str, Any]]:
        """Parse query result rows into result dicts."""
        results = []
        for row in rows:
            metadata = {}
            try:
                metadata = json.loads(row[4]) if row[4] else {}
            except json.JSONDecodeError:
                pass

            results.append({
                "id": row[0],
                "source": row[1],
                "source_type": row[2],
                "content": row[3],
                "metadata": {**metadata, "source": row[1], "source_type": row[2]},
                "distance": row[5],
            })
        return results

    async def aclear_source_type(self, source_type: str) -> None:
        """Clear all documents of a specific source type.

        Used before re-indexing to avoid stale data.

        Args:
            source_type: The source type to clear.
        """
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self._executor, self._clear_source_type_sync, source_type
        )

    def _clear_source_type_sync(self, source_type: str) -> None:
        """Synchronous clear by source type."""
        if not self._conn:
            return
        try:
            cursor = self._conn.cursor()
            # Get document IDs to clear vectors
            cursor.execute(
                "SELECT id FROM rag_documents WHERE source_type = ?",
                (source_type,),
            )
            doc_ids = [row[0] for row in cursor.fetchall()]

            if doc_ids:
                placeholders = ",".join("?" * len(doc_ids))
                cursor.execute(
                    f"DELETE FROM rag_vectors WHERE document_id IN ({placeholders})",
                    doc_ids,
                )
                cursor.execute(
                    f"DELETE FROM rag_documents WHERE id IN ({placeholders})",
                    doc_ids,
                )
                self._conn.commit()
                _LOGGER.debug("Cleared %d documents of type '%s'", len(doc_ids), source_type)
        except Exception as err:
            _LOGGER.error("Error clearing source type '%s': %s", source_type, err)

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
