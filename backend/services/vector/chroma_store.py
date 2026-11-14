"""
ChromaDB vector store (default backend).

Runs fully locally in embedded mode (``chromadb.PersistentClient``) and persists
to ``backend/storage/vectorstore``. The collection is created in **cosine** space
so a similarity score can be reported directly — brief §15 forbids made-up
relevance numbers, so the UI only ever shows the value the store actually returned.

Every failure (missing package, locked directory, corrupt index) is captured and
reported as a structured result instead of raising, so a broken vector database
never takes the whole API down (brief §22).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.vector.base import (
    SearchHit,
    VectorQueryResult,
    VectorRecord,
    VectorStore,
    VectorUpsertResult,
)

logger = logging.getLogger(__name__)

#: Chroma rejects very large batches, so upserts are chunked.
MAX_BATCH = 128


class ChromaVectorStore(VectorStore):
    """VectorStore implementation backed by an embedded Chroma database."""

    backend = "chroma"

    def __init__(self, collection_name: str, persist_dir: Path, *, space: str = "cosine") -> None:
        super().__init__(collection_name, persist_dir=str(persist_dir))
        self.space = space
        self._client = None
        self._collection = None
        self._error: Optional[str] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def _ensure(self):
        """Open the collection lazily; cache the first failure reason."""
        if self._collection is not None:
            return self._collection
        if self._error is not None:
            return None
        try:
            import chromadb

            Path(self.persist_dir or ".").mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self.persist_dir))
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": self.space},
            )
            logger.info("Chroma collection '%s' ready at %s", self.collection_name, self.persist_dir)
        except Exception as exc:  # noqa: BLE001 - report instead of crashing
            self._error = str(exc)
            logger.error("ChromaDB is unavailable: %s", exc)
            return None
        return self._collection

    @property
    def error(self) -> Optional[str]:
        self._ensure()
        return self._error

    def is_available(self) -> bool:
        return self._ensure() is not None

    def describe(self) -> Dict[str, Any]:
        payload = super().describe()
        payload["space"] = self.space
        payload["error"] = self.error
        return payload

    def close(self) -> None:
        """Release handles (used by tests that delete the storage directory)."""
        self._collection = None
        self._client = None
    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def upsert(self, records: List[VectorRecord]) -> VectorUpsertResult:
        if not records:
            return VectorUpsertResult(stored=0)
        try:
            for start in range(0, len(records), MAX_BATCH):
                self._upsert_batch(records[start : start + MAX_BATCH])
        except Exception as exc:  # noqa: BLE001 - report, never raise
            logger.error("Chroma upsert failed: %s", exc)
            return VectorUpsertResult(stored=0, ok=False, error=str(exc))
        return VectorUpsertResult(stored=len(records))

    def _upsert_batch(self, batch: List[VectorRecord]) -> None:
        collection = self._ensure()
        if collection is None:
            raise RuntimeError(self._error or "ChromaDB is unavailable")
        collection.upsert(
            ids=[record.id for record in batch],
            embeddings=[record.vector for record in batch],
            documents=[record.document for record in batch],
            metadatas=[self.clean_metadata(record.metadata) for record in batch],
        )

    def delete_document(self, document_id: str) -> int:
        collection = self._ensure()
        if collection is None:
            return 0
        try:
            removed = self._count_where({"document_id": document_id})
            collection.delete(where={"document_id": document_id})
            return removed
        except Exception as exc:  # noqa: BLE001
            logger.error("Chroma delete failed for document %s: %s", document_id, exc)
            return 0

    def delete_many(self, document_ids: List[str]) -> int:
        if not document_ids:
            return 0
        collection = self._ensure()
        if collection is None:
            return 0
        try:
            where = {"document_id": {"$in": list(document_ids)}}
            removed = self._count_where(where)
            collection.delete(where=where)
            return removed
        except Exception as exc:  # noqa: BLE001
            logger.error("Chroma bulk delete failed: %s", exc)
            return 0

    def delete_user(self, user_id: str) -> int:
        collection = self._ensure()
        if collection is None:
            return 0
        try:
            removed = self._count_where({"user_id": user_id})
            collection.delete(where={"user_id": user_id})
            return removed
        except Exception as exc:  # noqa: BLE001
            logger.error("Chroma user delete failed for %s: %s", user_id, exc)
            return 0

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def search(
        self,
        vector: List[float],
        *,
        top_k: int = 6,
        user_id: Optional[str] = None,
        document_ids: Optional[List[str]] = None,
        source_types: Optional[List[str]] = None,
    ) -> VectorQueryResult:
        started = time.perf_counter()
        collection = self._ensure()
        if collection is None:
            return VectorQueryResult(ok=False, error=self._error or "ChromaDB is unavailable")

        where = build_where(user_id=user_id, document_ids=document_ids, source_types=source_types)
        try:
            raw = collection.query(
                query_embeddings=[list(vector)],
                n_results=max(1, top_k),
                where=where or None,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:  # noqa: BLE001 - an empty collection raises here
            logger.error("Chroma query failed: %s", exc)
            return VectorQueryResult(ok=False, error=str(exc))

        return VectorQueryResult(
            hits=_hits_from_chroma(raw), ok=True, took_ms=int((time.perf_counter() - started) * 1000)
        )

    def count(self, *, user_id: Optional[str] = None) -> int:
        collection = self._ensure()
        if collection is None:
            return 0
        try:
            if user_id:
                return self._count_where({"user_id": user_id})
            return int(collection.count())
        except Exception as exc:  # noqa: BLE001
            logger.error("Chroma count failed: %s", exc)
            return 0

    def _count_where(self, where: Dict[str, Any]) -> int:
        collection = self._ensure()
        if collection is None:
            return 0
        result = collection.get(where=where, include=[])
        return len(result.get("ids") or [])

    # ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def build_where(
    *,
    user_id: Optional[str] = None,
    document_ids: Optional[List[str]] = None,
    source_types: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Build a Chroma ``where`` clause from the filters the UI can set.

    Chroma needs an explicit ``$and`` when several conditions are combined and
    ``$in`` for multi-value matches; this function hides that detail from the
    rest of the application.
    """
    clauses: List[Dict[str, Any]] = []
    if user_id:
        clauses.append({"user_id": user_id})
    if document_ids:
        clauses.append({"document_id": {"$in": list(document_ids)}})
    if source_types:
        clauses.append({"source_type": {"$in": list(source_types)}})
    if not clauses:
        return {}
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _hits_from_chroma(raw: Dict[str, Any]) -> List[SearchHit]:
    """Convert Chroma's column-oriented response into :class:`SearchHit` objects."""
    ids = (raw.get("ids") or [[]])[0]
    documents = (raw.get("documents") or [[]])[0]
    metadatas = (raw.get("metadatas") or [[]])[0]
    distances = (raw.get("distances") or [[]])[0]

    hits: List[SearchHit] = []
    for position, identifier in enumerate(ids):
        distance = distances[position] if position < len(distances) else None
        hits.append(
            SearchHit(
                id=str(identifier),
                text=(documents[position] if position < len(documents) else "") or "",
                distance=distance,
                # Cosine distance → similarity, so the UI can show a real number.
                score=round(1 - float(distance), 4) if distance is not None else None,
                metadata=(metadatas[position] if position < len(metadatas) else {}) or {},
            )
        )
    return hits