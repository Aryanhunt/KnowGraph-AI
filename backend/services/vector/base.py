"""
Vector store abstraction (brief §6).

``VectorStore`` is the contract; ChromaDB is the default implementation and a
pure-NumPy store is provided as a self-contained alternative (and for tests that
must not depend on Chroma internals).

Metadata is always carried *through* the vector store — document id, chunk id,
page number, title and source type travel with every vector, which is what makes
clickable source citations (brief §7) and per-document filtering possible.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class VectorRecord:
    """One chunk to upsert: id + vector + text + metadata."""

    id: str
    vector: List[float]
    document: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchHit:
    """One retrieval result, with everything needed for a citation."""

    id: str
    text: str = ""
    score: Optional[float] = None          # cosine similarity in [-1, 1] when available
    distance: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Convenience accessors used across services/routes.
    @property
    def document_id(self) -> str:
        return str(self.metadata.get("document_id", ""))

    @property
    def document_title(self) -> str:
        return str(self.metadata.get("title", ""))

    @property
    def chunk_id(self) -> str:
        return str(self.metadata.get("chunk_id", ""))

    @property
    def page_number(self) -> Optional[int]:
        page = self.metadata.get("page_number")
        try:
            return int(page)
        except (TypeError, ValueError):
            return None

    @property
    def source_type(self) -> str:
        return str(self.metadata.get("source_type", ""))

    def to_citation(self) -> Dict[str, Any]:
        """Shape used by the chat/search UI for the source list."""
        return {
            "document_id": self.document_id,
            "title": self.document_title,
            "page_number": self.page_number,
            "chunk_id": self.chunk_id,
            "snippet": (self.text or "")[:280],
            "score": self.score,
        }


@dataclass
class VectorUpsertResult:
    stored: int = 0
    ok: bool = True
    error: Optional[str] = None


@dataclass
class VectorQueryResult:
    hits: List[SearchHit] = field(default_factory=list)
    ok: bool = True
    error: Optional[str] = None
    took_ms: int = 0


class VectorStore(ABC):
    """Contract shared by Chroma and the NumPy store."""

    backend: str = "unknown"

    def __init__(self, collection_name: str, *, persist_dir: Optional[str] = None) -> None:
        self.collection_name = collection_name
        self.persist_dir = persist_dir

    # ------------------------------------------------------------------
    # Required behaviour
    # ------------------------------------------------------------------
    @abstractmethod
    def upsert(self, records: List[VectorRecord]) -> VectorUpsertResult:
        """Insert or replace vectors (idempotent by ``record.id``)."""

    @abstractmethod
    def search(
        self,
        vector: List[float],
        *,
        top_k: int = 6,
        user_id: Optional[str] = None,
        document_ids: Optional[List[str]] = None,
        source_types: Optional[List[str]] = None,
    ) -> VectorQueryResult:
        """Nearest-neighbour search with optional metadata filters."""

    @abstractmethod
    def delete_document(self, document_id: str) -> int:
        """Remove every vector of one document; returns how many were deleted."""

    @abstractmethod
    def count(self, *, user_id: Optional[str] = None) -> int:
        """Number of indexed vectors (optionally scoped to one user)."""

    @abstractmethod
    def is_available(self) -> bool:
        """True when the backing store can be used right now."""

    # ------------------------------------------------------------------
    # Optional behaviour
    # ------------------------------------------------------------------
    def delete_many(self, document_ids: List[str]) -> int:
        """Default: delete documents one by one."""
        return sum(self.delete_document(document_id) for document_id in document_ids)

    def delete_user(self, user_id: str) -> int:
        """Remove all vectors of a user (used when an account is deleted)."""
        return 0

    def describe(self) -> Dict[str, Any]:
        available = self.is_available()
        payload: Dict[str, Any] = {
            "backend": self.backend,
            "collection": self.collection_name,
            "persist_dir": self.persist_dir,
            "available": available,
        }
        if available:
            try:
                payload["vector_count"] = self.count()
            except Exception:  # pragma: no cover - store specific
                payload["vector_count"] = None
        return payload

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------
    @staticmethod
    def clean_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Make metadata safe for Chroma, which only accepts str/int/float/bool.

        ``None`` becomes ``""`` and lists are joined, so nothing is lost and no
        store rejects the record.
        """
        cleaned: Dict[str, Any] = {}
        for key, value in (metadata or {}).items():
            if value is None:
                cleaned[key] = ""
            elif isinstance(value, (str, int, float, bool)):
                cleaned[key] = value
            elif isinstance(value, (list, tuple, set)):
                cleaned[key] = ", ".join(str(item) for item in value)
            else:
                cleaned[key] = str(value)
        return cleaned