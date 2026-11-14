"""Vector storage services (ChromaDB default, NumPy fallback)."""

from services.vector.base import (
    SearchHit,
    VectorQueryResult,
    VectorRecord,
    VectorStore,
    VectorUpsertResult,
)
from services.vector.factory import (
    BACKENDS,
    build_vector_store,
    get_vector_store,
    reset_vector_store,
    vector_store_status,
)

__all__ = [
    "SearchHit",
    "VectorQueryResult",
    "VectorRecord",
    "VectorStore",
    "VectorUpsertResult",
    "BACKENDS",
    "build_vector_store",
    "get_vector_store",
    "reset_vector_store",
    "vector_store_status",
]