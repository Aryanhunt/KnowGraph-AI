"""
Deterministic "hashing" embedding provider.

Why it exists: the project must be testable and runnable on a machine that has
not pulled an embedding model yet. This provider needs no model download and no
network — it maps tokens into a fixed-size vector with the hashing trick
(signed counts, then L2 normalised).

It is honest about what it is: it captures *lexical* overlap only, so it is used
for tests, demos and offline development, and never presented as a semantic
model. The provider name is stored with every vector so the UI can say which
embedder indexed the data.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List

from services.embeddings.base import EmbeddingResult, EmbeddingService
from utils.text import _WORD

PROVIDER_NAME = "hashing"


class HashingEmbeddingService(EmbeddingService):
    """Model-free, deterministic embedding provider (lexical similarity only)."""

    provider = PROVIDER_NAME

    def __init__(self, model: str = "hashing-bow", *, dimension: int = 512, **_: Any) -> None:
        super().__init__(model, timeout_seconds=1, batch_size=256)
        self._dimension = max(64, dimension)
        self.model = model or "hashing-bow"

    def is_available(self) -> bool:
        return True

    def unavailable_reason(self) -> str:
        return ""

    def describe(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "available": True,
            "dimension": self._dimension,
            "error": None,
            "note": "Deterministic lexical embedder — no ML model involved (used for tests/offline mode).",
        }

    def embed_texts(self, texts: List[str]) -> EmbeddingResult:
        started = time.perf_counter()
        vectors = [self._embed_one(text or "") for text in texts]
        return EmbeddingResult(
            vectors=vectors,
            model=self.model,
            provider=self.provider,
            dimension=self._dimension,
            ok=True,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    def _embed_one(self, text: str) -> List[float]:
        """Hashing trick: each token increments one bucket, signed by a second hash."""
        vector = [0.0] * self._dimension
        for token in _WORD.findall(text.lower()):
            digest = hashlib.md5(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        return self.l2_normalize(vector)