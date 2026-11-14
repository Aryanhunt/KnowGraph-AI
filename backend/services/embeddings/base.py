"""
Embedding abstraction (brief §6).

``EmbeddingService`` is the only embedding interface the application uses:

* ``embed_texts``  — index document chunks,
* ``embed_query``  — embed a search question / chat question,
* ``is_available`` — honest status for the health endpoint,
* ``describe``     — provider/model/dimension for the settings page.

The provider and model names always come from configuration, so switching from
``nomic-embed-text`` to another local model never requires a code change.

Important: vectors from different models are not comparable, so the pipeline
never silently swaps the model inside an existing index. If the configured
provider is unavailable the document is marked failed with an actionable message
instead of being indexed with a different (mismatched) vector space.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EmbeddingResult:
    """Outcome of one embedding batch."""

    vectors: List[List[float]] = field(default_factory=list)
    model: str = ""
    provider: str = ""
    dimension: int = 0
    ok: bool = True
    error: Optional[str] = None
    duration_ms: int = 0

    def __len__(self) -> int:
        return len(self.vectors)


class EmbeddingService(ABC):
    """Contract every embedding provider must implement."""

    provider: str = "unknown"

    def __init__(self, model: str, *, timeout_seconds: int = 60, batch_size: int = 16) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.batch_size = max(1, batch_size)
        self._dimension: int = 0

    # ------------------------------------------------------------------
    # Required behaviour
    # ------------------------------------------------------------------
    @abstractmethod
    def embed_texts(self, texts: List[str]) -> EmbeddingResult:
        """Embed a list of passages (order is preserved)."""

    @abstractmethod
    def is_available(self) -> bool:
        """Cheap reachability probe that never raises."""

    def embed_query(self, query: str) -> List[float]:
        """
        Embed a search query.

        Default implementation reuses :meth:`embed_texts`; providers that need a
        different query prefix (some models do) can override this.
        """
        result = self.embed_texts([query])
        if not result.ok or not result.vectors:
            from utils.errors import LocalServiceUnavailableError

            raise LocalServiceUnavailableError(
                "The embedding model could not process the question.",
                code="embedding_failed",
                hint=result.error or "Check that the embedding model is installed.",
            )
        return result.vectors[0]

    # ------------------------------------------------------------------
    # Optional behaviour
    # ------------------------------------------------------------------
    @property
    def dimension(self) -> int:
        """Dimension of produced vectors (0 until a vector has been produced)."""
        return self._dimension

    def describe(self) -> Dict[str, Any]:
        available = self.is_available()
        return {
            "provider": self.provider,
            "model": self.model,
            "available": available,
            "dimension": self.dimension or None,
            "error": None if available else self.unavailable_reason(),
        }

    def unavailable_reason(self) -> str:
        return f"The {self.provider} embedding provider is not available."

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _store_dimension(self, vectors: List[List[float]]) -> None:
        if vectors and vectors[0]:
            self._dimension = len(vectors[0])

    @staticmethod
    def l2_normalize(vector: List[float]) -> List[float]:
        """
        Unit-normalise a vector.

        Cosine similarity is then a plain dot product, which keeps the NumPy
        vector store and Chroma (configured for cosine space) consistent.
        """
        import math

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]