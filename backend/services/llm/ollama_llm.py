"""
Ollama adapter — local LLM inference over HTTP.

Ollama exposes a small REST API on ``http://127.0.0.1:11434`` by default. This
adapter is the only place in the project that speaks that protocol, so every
model name and endpoint comes from :mod:`config.settings`.

Requirements honoured here:
* no online LLM API is contacted (brief §2),
* the model is configurable and never hard-coded (brief §26.3),
* "Ollama is not running" produces a friendly error, not a crash (brief §22).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import requests

from services.llm.base import LLMMessage, LLMResponse, LLMService
from utils.errors import LocalServiceUnavailableError, ollama_model_missing, ollama_unavailable

logger = logging.getLogger(__name__)


class OllamaLLMService(LLMService):
    """LLMService implementation backed by a local Ollama daemon."""

    provider = "ollama"

    def __init__(
        self,
        model: str,
        *,
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: int = 180,
        temperature: float = 0.1,
        num_ctx: int = 8192,
        max_tokens: int = 1024,
    ) -> None:
        super().__init__(model, timeout_seconds=timeout_seconds, temperature=temperature)
        self.base_url = base_url.rstrip("/")
        self.num_ctx = num_ctx
        self.max_tokens = max_tokens

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    def _options(self, temperature: Optional[float], max_tokens: Optional[int]) -> Dict[str, Any]:
        """Ollama runtime options; keeps the model context window explicit."""
        return {
            "temperature": self.temperature if temperature is None else temperature,
            "num_predict": self.max_tokens if max_tokens is None else max_tokens,
            "num_ctx": self.num_ctx,
        }

    def _post(self, path: str, payload: Dict[str, Any], *, timeout: Optional[int] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            response = requests.post(url, json=payload, timeout=timeout or self.timeout_seconds)
        except requests.exceptions.ConnectionError as exc:
            raise ollama_unavailable(self.model, self.base_url) from exc
        except requests.exceptions.Timeout as exc:
            raise LocalServiceUnavailableError(
                "The local model took too long to answer.",
                code="llm_timeout",
                hint="Try a smaller model (LLM_MODEL in backend/.env) or a shorter question.",
                details={"model": self.model, "timeout_seconds": self.timeout_seconds},
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise ollama_unavailable(self.model, self.base_url) from exc

        if response.status_code == 404:
            # Ollama answers 404 when the requested model is not installed.
            raise ollama_model_missing(self.model)
        if response.status_code >= 400:
            raise LocalServiceUnavailableError(
                f"Ollama rejected the request (HTTP {response.status_code}).",
                code="llm_request_failed",
                hint="Check backend/logs/app.log for the Ollama response body.",
                details={"model": self.model, "body": response.text[:400]},
            )
        try:
            return response.json()
        except ValueError as exc:  # pragma: no cover - malformed daemon response
            raise LocalServiceUnavailableError(
                "Ollama returned an unreadable response.",
                code="llm_bad_response",
                hint="Restart Ollama and try again.",
            ) from exc

# ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    def generate(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": self._options(temperature, max_tokens),
        }
        if system:
            payload["system"] = system

        started = time.perf_counter()
        data = self._post("/api/generate", payload)
        return self._to_response(data.get("response", ""), prompt, data, started)

    def chat(
        self,
        messages: List[LLMMessage],
        *,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        wire_messages: List[Dict[str, str]] = []
        if system:
            wire_messages.append({"role": "system", "content": system})
        wire_messages.extend({"role": message.role, "content": message.content} for message in messages)

        prompt_chars = sum(len(message["content"]) for message in wire_messages)
        payload = {
            "model": self.model,
            "messages": wire_messages,
            "stream": False,
            "options": self._options(temperature, max_tokens),
        }

        started = time.perf_counter()
        data = self._post("/api/chat", payload)
        text = ((data.get("message") or {}).get("content") or "").strip()
        return LLMResponse(
            text=text,
            model=str(data.get("model", self.model)),
            provider=self.provider,
            ok=bool(text),
            error=None if text else "empty_response",
            duration_ms=int((time.perf_counter() - started) * 1000),
            prompt_chars=prompt_chars,
            usage={
                "eval_count": data.get("eval_count"),
                "prompt_eval_count": data.get("prompt_eval_count"),
            },
        )

    @staticmethod
    def _to_response(text: str, prompt: str, data: Dict[str, Any], started: float) -> LLMResponse:
        cleaned = (text or "").strip()
        return LLMResponse(
            text=cleaned,
            model=str(data.get("model", "")),
            provider="ollama",
            ok=bool(cleaned),
            error=None if cleaned else "empty_response",
            duration_ms=int((time.perf_counter() - started) * 1000),
            prompt_chars=len(prompt or ""),
            usage={
                "eval_count": data.get("eval_count"),
                "prompt_eval_count": data.get("prompt_eval_count"),
                "done_reason": data.get("done_reason"),
            },
        )

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    def is_available(self) -> bool:
        """Short silent probe — used by the health endpoint and the UI banner."""
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
        names = [
            str(entry.get("name") or entry.get("model"))
            for entry in (data.get("models") or [])
            if entry.get("name") or entry.get("model")
        ]
        return sorted(names)

    def health(self) -> Dict[str, Any]:
        status = super().health()
        status["base_url"] = self.base_url
        status["num_ctx"] = self.num_ctx
        return status