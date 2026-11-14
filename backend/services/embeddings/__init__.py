"""Embedding services (local only)."""

from services.embeddings.base import EmbeddingResult, EmbeddingService
from services.embeddings.factory import (
    PROVIDERS,
    build_embedding_service,
    get_embedding_service,
    reset_embedding_service,
)

__all__ = [
    "EmbeddingResult",
    "EmbeddingService",
    "PROVIDERS",
    "build_embedding_service",
    "get_embedding_service",
    "reset_embedding_service",
]