"""
LLM abstraction.

``LLMService`` is the *only* interface the rest of the application knows about, so
swapping the local model (or even the runtime) never leaks into business logic
(brief §19). :class:`~services.llm.ollama_llm.OllamaLLMService` is the shipped
implementation and talks to a local Ollama server over HTTP — no online AI
provider exists anywhere in this project.

Implementations must never raise on "server not running" but raise a friendly
``AppError``, must return an :class:`LLMResponse` describing what really
happened, and must stay honest so callers can fall back to deterministic
algorithms when the model is unavailable.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.errors import LocalServiceUnavailableError

# Matches the first fenced JSON block, which small local models often add.
_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


@dataclass
class LLMMessage:
    """A single chat message handed to the model."""

    role: str          # system | user | assistant
    content: str


@dataclass
class LLMResponse:
    """Outcome of one generation, including diagnostics for the UI/API."""

    text: str = ""
    model: str = ""
    provider: str = ""
    ok: bool = True
    error: Optional[str] = None
    duration_ms: int = 0
    prompt_chars: int = 0
    usage: Dict[str, Any] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not (self.text or "").strip()


class LLMService(ABC):
    """Interface every local LLM adapter must implement."""

    provider: str = "unknown"

    def __init__(self, model: str, *, timeout_seconds: int = 120, temperature: float = 0.1) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature

    # -- required behaviour ------------------------------------------------
    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Single-shot completion."""

    @abstractmethod
    def chat(
        self,
        messages: List[LLMMessage],
        *,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Multi-turn completion."""

    @abstractmethod
    def is_available(self) -> bool:
        """Cheap reachability probe (never raises)."""

    # -- optional behaviour ------------------------------------------------
    def list_models(self) -> List[str]:
        """Locally installed models, when the runtime can report them."""
        return []

    def has_model(self, model: Optional[str] = None) -> bool:
        target = model or self.model
        installed = self.list_models()
        if not installed:
            return False
        return any(name == target or name.split(":")[0] == target for name in installed)

    def health(self) -> Dict[str, Any]:
        """Structured status for ``GET /api/system/health``."""
        available = self.is_available()
        return {
            "provider": self.provider,
            "model": self.model,
            "available": available,
            "model_installed": self.has_model() if available else False,
            "installed_models": self.list_models() if available else [],
        }

    # -- convenience -------------------------------------------------------
    def generate_json(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Ask for JSON and parse it defensively.

        Returns ``None`` when the model is unavailable or produced something
        unparsable, so callers fall back to deterministic logic rather than
        presenting nonsense to the user.
        """
        try:
            response = self.generate(prompt, system=system, max_tokens=max_tokens)
        except LocalServiceUnavailableError:
            return None
        if not response.ok or response.empty:
            return None
        return parse_json_response(response.text)


def parse_json_response(text: str) -> Optional[Dict[str, Any]]:
    """
    Extract the first JSON object/array from a model answer.

    Handles ```json fences plus leading/trailing prose, which small local models
    produce constantly. Arrays are wrapped as ``{"items": [...]}`` so callers
    always receive a dict.
    """
    if not text:
        return None

    candidates: List[str] = []
    fenced = _JSON_BLOCK.search(text)
    if fenced:
        candidates.append(fenced.group(1).strip())
    candidates.append(text.strip())

    for candidate in candidates:
        parsed = _attempt_load(candidate)
        if parsed is None:
            # Retry from the first brace/bracket to skip any preamble.
            positions = [index for index in (candidate.find("{"), candidate.find("[")) if index != -1]
            if positions:
                parsed = _attempt_load(candidate[min(positions):])
        if parsed is None:
            continue
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"items": parsed}
    return None


def _attempt_load(candidate: str) -> Optional[Any]:
    """Try ``json.loads``, then repair the two most common model mistakes."""
    for attempt in (candidate, _trim_to_last_brace(candidate), _strip_trailing_commas(candidate)):
        if not attempt:
            continue
        try:
            return json.loads(attempt)
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _trim_to_last_brace(text: str) -> str:
    """Cut the text at its last closing brace (drops trailing commentary)."""
    last_object = max(text.rfind("}"), text.rfind("]"))
    return text[: last_object + 1] if last_object != -1 else text


def _strip_trailing_commas(text: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", text)