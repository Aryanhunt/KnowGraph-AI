"""
Pure-NumPy vector store (no external dependency).

Why it exists:
* it makes the vector layer genuinely replaceable (brief §6/§19),
* it gives the test suite a fast, deterministic store with no Chroma internals,
* it is a working fallback for machines where ChromaDB cannot be installed —
  set ``VECTOR_DB=numpy`` in ``backend/.env``.

It performs exact (brute-force) cosine search over a persistent ``.npy`` matrix.
For a personal knowledge base (thousands of chunks) this is fast enough and 100%
explainable in a viva: the score shown in the UI is a real dot product of
normalised vectors.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from services.vector.base import (
    SearchHit,
    VectorQueryResult,
    VectorRecord,
    VectorStore,
    VectorUpsertResult,
)

logger = logging.getLogger(__name__)


class NumpyVectorStore(VectorStore):
    """Exact cosine-similarity vector store persisted as .npy + .json."""

    backend = "numpy"

    def __init__(self, collection_name: str, persist_dir: Path) -> None:
        super().__init__(collection_name, persist_dir=str(persist_dir))
        self._dir = Path(persist_dir) / "numpy"
        self._vectors_path = self._dir / f"{collection_name}.npy"
        self._records_path = self._dir / f"{collection_name}.records.json"
        self._vectors: Optional[np.ndarray] = None
        self._records: List[Dict[str, Any]] = []
        self._index: Dict[str, int] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load(self) -> None:
        try:
            if self._vectors_path.exists() and self._records_path.exists():
                matrix = np.load(self._vectors_path)
                with open(self._records_path, "r", encoding="utf-8") as handle:
                    records = json.load(handle)
                if len(records) == matrix.shape[0]:
                    self._vectors = matrix.astype(np.float32)
                    self._records = records
                    self._index = {record["id"]: position for position, record in enumerate(records)}
        except Exception as exc:  # noqa: BLE001 - a corrupt file must not kill the app
            logger.error("Could not load the NumPy vector index: %s", exc)
            self._vectors, self._records, self._index = None, [], {}

    def _save(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        if self._vectors is not None:
            np.save(self._vectors_path, self._vectors)
        with open(self._records_path, "w", encoding="utf-8") as handle:
            json.dump(self._records, handle)

    def is_available(self) -> bool:
        return True

    def describe(self) -> Dict[str, Any]:
        payload = super().describe()
        payload["space"] = "cosine"
        payload["mode"] = "exact brute-force search (no index approximation)"
        return payload

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def upsert(self, records: List[VectorRecord]) -> VectorUpsertResult:
        if not records:
            return VectorUpsertResult(stored=0)
        try:
            for record in records:
                vector = np.asarray(record.vector, dtype=np.float32)
                payload = {"id": record.id, "document": record.document,
                           "metadata": self.clean_metadata(record.metadata)}
                position = self._index.get(record.id)
                if position is None:
                    self._index[record.id] = len(self._records)
                    self._records.append(payload)
                    self._vectors = (
                        vector.reshape(1, -1) if self._vectors is None
                        else np.vstack([self._vectors, vector.reshape(1, -1)])
                    )
                else:
                    self._records[position] = payload
                    assert self._vectors is not None
                    self._vectors[position] = vector
            self._save()
        except Exception as exc:  # noqa: BLE001 - report, never raise
            logger.error("NumPy vector upsert failed: %s", exc)
            return VectorUpsertResult(stored=0, ok=False, error=str(exc))
        return VectorUpsertResult(stored=len(records))

    def _drop_positions(self, positions: set) -> int:
        if not positions:
            return 0
        keep = [index for index in range(len(self._records)) if index not in positions]
        self._records = [self._records[index] for index in keep]
        if self._vectors is not None:
            self._vectors = self._vectors[keep] if keep else None
        self._index = {record["id"]: position for position, record in enumerate(self._records)}
        self._save()
        return len(positions)

    def delete_document(self, document_id: str) -> int:
        positions = {
            index
            for index, record in enumerate(self._records)
            if record.get("metadata", {}).get("document_id") == document_id
        }
        return self._drop_positions(positions)

    def delete_many(self, document_ids: List[str]) -> int:
        wanted = set(document_ids or [])
        positions = {
            index
            for index, record in enumerate(self._records)
            if record.get("metadata", {}).get("document_id") in wanted
        }
        return self._drop_positions(positions)

    def delete_user(self, user_id: str) -> int:
        positions = {
            index
            for index, record in enumerate(self._records)
            if record.get("metadata", {}).get("user_id") == user_id
        }
        return self._drop_positions(positions)

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
        if self._vectors is None or not self._records:
            return VectorQueryResult(hits=[], ok=True, took_ms=0)

        query = np.asarray(vector, dtype=np.float32)
        if query.shape[0] != self._vectors.shape[1]:
            return VectorQueryResult(
                ok=False,
                error=(
                    "The question was embedded with a different model than the stored document "
                    f"(query dim {query.shape[0]} vs index dim {self._vectors.shape[1]})."
                ),
            )

        # Vectors are stored normalised, so the dot product *is* cosine similarity.
        similarities = self._vectors @ query
        order = np.argsort(-similarities)

        wanted = set(document_ids or [])
        allowed_sources = set(source_types or [])

        hits: List[SearchHit] = []
        for position in order:
            metadata = self._records[int(position)].get("metadata", {})
            if user_id and metadata.get("user_id") != user_id:
                continue
            if wanted and metadata.get("document_id") not in wanted:
                continue
            if allowed_sources and metadata.get("source_type") not in allowed_sources:
                continue
            hits.append(
                SearchHit(
                    id=str(self._records[int(position)]["id"]),
                    text=self._records[int(position)].get("document", ""),
                    score=round(float(similarities[int(position)]), 4),
                    distance=round(1 - float(similarities[int(position)]), 4),
                    metadata=metadata,
                )
            )
            if len(hits) >= max(1, top_k):
                break

        return VectorQueryResult(hits=hits, ok=True, took_ms=int((time.perf_counter() - started) * 1000))

    def count(self, *, user_id: Optional[str] = None) -> int:
        if not user_id:
            return len(self._records)
        return sum(
            1 for record in self._records if record.get("metadata", {}).get("user_id") == user_id
        )

    def close(self) -> None:
        """Release state (used by tests that delete the storage directory)."""
        self._vectors, self._records, self._index = None, [], {}