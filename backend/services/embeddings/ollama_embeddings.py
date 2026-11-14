"""
Ollama embedding adapter.

Uses the same local Ollama daemon as the chat model, so no extra service is
needed and no data leaves the machine (brief §2/§23). The vector dimension is
discovered from the first response rather than assumed, which keeps the vector
store consistent when a different local embedding model is configured.

Ollama exposes two embedding endpoints:
* ``POST /api/embed``       — modern, batch input (preferred),
* ``POST /api/embeddings``  — legacy, one prompt at a time (fallback so an older
  daemon still works).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

import requests

from services.embeddings.base import EmbeddingResult, EmbeddingService
from utils.errors import LocalServiceUnavailableError, ollama_model_missing, ollama_unavailable

logger = logging.getLogger(__name__)


class OllamaEmbeddingService(EmbeddingService):
    """EmbeddingService implementation backed by a local Ollama daemon."""

    provider = "ollama"

    def __init__(
        self,
        model: str,
        *,
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: int = 60,
        batch_size: int = 16,
    ) -> None:
        super().__init__(model, timeout_seconds=timeout_seconds, batch_size=batch_size)
        self.base_url = base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------
    def is_available(self) -> bool:
        try:
            return requests.get(f"{self.base_url}/api/tags", timeout=2.5).status_code == 200
        except requests.exceptions.RequestException:
            return False

    def list_models(self) -> List[str]:
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code != 200:
                return []
            data = response.json()
        except (requests.exceptions.RequestException, ValueError):
            return []
        return sorted(
            str(entry.get("name") or entry.get("model"))
            for entry in (data.get("models") or [])
            if entry.get("name") or entry.get("model")
        )

    def has_model(self) -> bool:
        installed = self.list_models()
        if not installed:
            return False
        return any(name == self.model or name.split(":")[0] == self.model for name in installed)

    def unavailable_reason(self) -> str:
        if not self.is_available():
            return f"Ollama is not running at {self.base_url}."
        if not self.has_model():
            return f"The embedding model '{self.model}' is not installed (run `ollama pull {self.model}`)."
        return "The Ollama embedding endpoint is not reachable."

    def describe(self) -> Dict[str, Any]:
        status = super().describe()
        status["base_url"] = self.base_url
        return status

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------
    def embed_texts(self, texts: List[str]) -> EmbeddingResult:
        started = time.perf_counter()
        cleaned = [(text or "").strip() for text in texts]
        if not cleaned:
            return EmbeddingResult(vectors=[], model=self.model, provider=self.provider, ok=True)

        vectors: List[List[float]] = []
        try:
            for start in range(0, len(cleaned), self.batch_size):
                vectors.extend(self._embed_batch(cleaned[start : start + self.batch_size]))
        except LocalServiceUnavailableError as exc:
            # Reported, not raised: the pipeline decides how to record the failure.
            return EmbeddingResult(
                vectors=[],
                model=self.model,
                provider=self.provider,
                ok=False,
                error=exc.message,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

        self._store_dimension(vectors)
        return EmbeddingResult(
            vectors=vectors,
            model=self.model,
            provider=self.provider,
            dimension=self.dimension,
            ok=len(vectors) == len(cleaned),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    def _embed_batch(self, batch: List[str]) -> List[List[float]]:
        """Call ``/api/embed``; transparently fall back to the legacy endpoint."""
        try:
            response = requests.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": batch},
                timeout=self.timeout_seconds,
            )
        except requests.exceptions.ConnectionError as exc:
            raise ollama_unavailable(self.model, self.base_url) from exc
        except requests.exceptions.Timeout as exc:
            raise LocalServiceUnavailableError(
                "The embedding model took too long to respond.",
                code="embedding_timeout",
                hint="Use a smaller embedding model or raise EMBEDDING_TIMEOUT_SECONDS.",
                details={"model": self.model},
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise ollama_unavailable(self.model, self.base_url) from exc

        if response.status_code == 404:
            # Older daemon or missing model — try the legacy single-prompt API.
            return self._embed_legacy(batch)
        if response.status_code >= 400:
            raise LocalServiceUnavailableError(
                f"Ollama rejected the embedding request (HTTP {response.status_code}).",
                code="embedding_request_failed",
                hint="Verify EMBEDDING_MODEL exists locally with `ollama list`.",
                details={"model": self.model, "body": response.text[:300]},
            )

        embeddings = response.json().get("embeddings") or []
        if len(embeddings) != len(batch):
            raise LocalServiceUnavailableError(
                "The embedding model returned an unexpected number of vectors.",
                code="embedding_count_mismatch",
                details={"expected": len(batch), "received": len(embeddings)},
            )
        return [[float(value) for value in vector] for vector in embeddings]

    def _embed_legacy(self, batch: List[str]) -> List[List[float]]:
        vectors: List[List[float]] = []
        for text in batch:
            try:
                response = requests.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                    timeout=self.timeout_seconds,
                )
            except requests.exceptions.ConnectionError as exc:
                raise ollama_unavailable(self.model, self.base_url) from exc
            except requests.exceptions.RequestException as exc:
                raise ollama_unavailable(self.model, self.base_url) from exc

            if response.status_code == 404:
                raise ollama_model_missing(self.model)
            if response.status_code >= 400:
                raise LocalServiceUnavailableError(
                    f"Ollama rejected the embedding request (HTTP {response.status_code}).",
                    code="embedding_request_failed",
                    details={"model": self.model, "body": response.text[:300]},
                )
            vector = response.json().get("embedding") or []
            if not vector:
                raise LocalServiceUnavailableError(
                    "The embedding model returned an empty vector.",
                    code="embedding_empty",
                    details={"model": self.model},
                )
            vectors.append([float(value) for value in vector])
        return vectors