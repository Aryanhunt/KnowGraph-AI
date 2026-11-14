"""
Vector store factory.

``VECTOR_DB`` in ``backend/.env`` selects the backend:

* ``chroma`` — embedded ChromaDB (default), cosine space, persistent,
* ``numpy``  — exact brute-force cosine search with no extra dependency.

Both implementations satisfy :class:`~services.vector.base.VectorStore`, so the
RAG pipeline and the search service never know which one is active.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Type

from config.settings import Settings, get_settings
from services.vector.base import VectorStore
from services.vector.chroma_store import ChromaVectorStore
from services.vector.numpy_store import NumpyVectorStore
from utils.errors import ConfigurationError, vector_store_unavailable
from utils.logging_setup import get_logger

logger = get_logger(__name__)

BACKENDS: Dict[str, Type[VectorStore]] = {
    "chroma": ChromaVectorStore,
    "numpy": NumpyVectorStore,
}

_store: Optional[VectorStore] = None
_store_key: Optional[tuple] = None


def build_vector_store(settings: Optional[Settings] = None) -> VectorStore:
    """Create a new vector store instance (no caching)."""
    current = settings or get_settings()
    backend = (current.vector_db or "chroma").lower()

    if backend not in BACKENDS:
        raise ConfigurationError(
            f"Unknown VECTOR_DB '{backend}'.",
            hint=f"Supported backends: {', '.join(sorted(BACKENDS))}.",
        )

    persist_dir = Path(current.vector_dir)
    persist_dir.mkdir(parents=True, exist_ok=True)

    if backend == "numpy":
        return NumpyVectorStore(current.chroma_collection, persist_dir)
    return ChromaVectorStore(current.chroma_collection, persist_dir)


def get_vector_store(settings: Optional[Settings] = None) -> VectorStore:
    """
    Cached vector store.

    Raises a friendly error only when the backend truly cannot be opened, so the
    API reports "the local vector database is unavailable" with a hint instead of
    returning a 500 traceback.
    """
    global _store, _store_key
    current = settings or get_settings()
    key = (current.vector_db, current.chroma_collection, str(current.vector_dir))
    if _store is None or _store_key != key:
        store = build_vector_store(current)
        if not store.is_available():
            reason = str(getattr(store, "error", "") or "backend could not be opened")
            raise vector_store_unavailable(reason)
        _store = store
        _store_key = key
        logger.info("Vector store ready: %s", store.describe())
    return _store


def vector_store_status(settings: Optional[Settings] = None) -> Dict[str, object]:
    """Non-raising status probe used by ``GET /api/system/health``."""
    try:
        store = get_vector_store(settings)
        return store.describe()
    except Exception as exc:  # noqa: BLE001 - health checks must never raise
        current = settings or get_settings()
        return {
            "backend": current.vector_db,
            "collection": current.chroma_collection,
            "available": False,
            "error": getattr(exc, "message", str(exc)),
        }


def reset_vector_store() -> None:
    """Drop the cached store (used by tests and after a settings change)."""
    global _store, _store_key
    if _store is not None and hasattr(_store, "close"):
        try:
            _store.close()  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - best effort cleanup
            pass
    _store = None
    _store_key = None