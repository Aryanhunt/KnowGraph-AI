"""
Embedding factory.

``EMBEDDING_PROVIDER`` in ``backend/.env`` selects the implementation:

* ``ollama``  — a real local embedding model (default, best quality),
* ``hashing`` — deterministic, model-free embedder for tests/offline mode.

Note the deliberate design choice: the factory never swaps providers behind the
caller's back. Vectors from different models are not comparable, and mixing them
inside one vector collection would silently corrupt search results. If the
configured provider is unavailable, :func:`get_embedding_service` still returns
the configured service and the *caller* reports the failure (the pipeline marks
the document failed with an actionable message).
"""

from __future__ import annotations

from typing import Dict, Optional, Type

from config.settings import Settings, get_settings
from services.embeddings.base import EmbeddingService
from services.embeddings.hashing_embeddings import HashingEmbeddingService
from services.embeddings.ollama_embeddings import OllamaEmbeddingService
from utils.errors import ConfigurationError
from utils.logging_setup import get_logger

logger = get_logger(__name__)

#: Supported embedding providers.
PROVIDERS: Dict[str, Type[EmbeddingService]] = {
    "ollama": OllamaEmbeddingService,
    "hashing": HashingEmbeddingService,
}

BLOCKED_PROVIDERS = {"openai", "cohere", "gemini", "google", "voyage", "azure"}

_service: Optional[EmbeddingService] = None
_service_key: Optional[tuple] = None


def build_embedding_service(settings: Optional[Settings] = None) -> EmbeddingService:
    """Create a new embedding service instance (no caching)."""
    current = settings or get_settings()
    provider = (current.embedding_provider or "ollama").lower()

    if provider in BLOCKED_PROVIDERS:
        raise ConfigurationError(
            f"EMBEDDING_PROVIDER='{provider}' is a hosted provider and is not allowed.",
            hint="KnowGraph AI embeds locally. Use EMBEDDING_PROVIDER=ollama (or hashing for tests).",
        )
    if provider not in PROVIDERS:
        raise ConfigurationError(
            f"Unknown EMBEDDING_PROVIDER '{provider}'.",
            hint=f"Supported providers: {', '.join(sorted(PROVIDERS))}.",
        )

    if provider == "hashing":
        logger.info("Using deterministic hashing embeddings (dim=%s)", current.hashing_embedding_dim)
        return HashingEmbeddingService(
            "hashing-bow", dimension=current.hashing_embedding_dim
        )

    logger.info("Using Ollama embeddings model=%s", current.embedding_model)
    return OllamaEmbeddingService(
        current.embedding_model,
        base_url=current.ollama_base_url,
        timeout_seconds=current.embedding_timeout_seconds,
    )


def get_embedding_service(settings: Optional[Settings] = None) -> EmbeddingService:
    """Cached embedding service, rebuilt when the configuration changes."""
    global _service, _service_key
    current = settings or get_settings()
    key = (
        current.embedding_provider,
        current.embedding_model,
        current.ollama_base_url,
        current.embedding_timeout_seconds,
        current.hashing_embedding_dim,
    )
    if _service is None or _service_key != key:
        _service = build_embedding_service(current)
        _service_key = key
    return _service


def reset_embedding_service() -> None:
    """Drop the cached service (used by tests and after a settings change)."""
    global _service, _service_key
    _service = None
    _service_key = None