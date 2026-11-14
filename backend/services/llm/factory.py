"""
LLM factory — the single place that decides which local runtime is used.

``LLM_PROVIDER`` in ``backend/.env`` selects the implementation. Online providers
are *explicitly rejected* here so the "local AI only" rule from brief §2 cannot be
broken by accident: adding ``LLM_PROVIDER=openai`` produces a configuration error
instead of silently calling a paid API.
"""

from __future__ import annotations

from typing import Dict, Optional, Type

from config.settings import Settings, get_settings
from services.llm.base import LLMService
from services.llm.ollama_llm import OllamaLLMService
from utils.errors import ConfigurationError
from utils.logging_setup import get_logger

logger = get_logger(__name__)

#: Supported local runtimes. Add a class here to support another one.
PROVIDERS: Dict[str, Type[LLMService]] = {
    "ollama": OllamaLLMService,
}

#: Providers that would send documents to a third party — never allowed.
BLOCKED_PROVIDERS = {"openai", "anthropic", "gemini", "google", "groq", "claude", "azure", "bedrock"}

_service: Optional[LLMService] = None
_service_key: Optional[tuple] = None


def build_llm_service(settings: Optional[Settings] = None) -> LLMService:
    """Create a new LLM service instance (no caching)."""
    current = settings or get_settings()
    provider = (current.llm_provider or "ollama").lower()

    if provider in BLOCKED_PROVIDERS:
        raise ConfigurationError(
            f"LLM_PROVIDER='{provider}' is an online provider and is not allowed.",
            hint="KnowGraph AI is local-first. Use LLM_PROVIDER=ollama.",
            details={"blocked_providers": sorted(BLOCKED_PROVIDERS)},
        )
    if provider not in PROVIDERS:
        raise ConfigurationError(
            f"Unknown LLM_PROVIDER '{provider}'.",
            hint=f"Supported providers: {', '.join(sorted(PROVIDERS))}.",
        )

    service_cls = PROVIDERS[provider]
    logger.info("Using LLM provider=%s model=%s", provider, current.llm_model)
    return service_cls(
        current.llm_model,
        base_url=current.ollama_base_url,
        timeout_seconds=current.llm_timeout_seconds,
        temperature=current.llm_temperature,
        num_ctx=current.llm_num_ctx,
        max_tokens=current.llm_max_tokens,
    )


def get_llm_service(settings: Optional[Settings] = None) -> LLMService:
    """
    Cached LLM service.

    The cache key includes provider/model/url/timeouts so that changing the
    configuration (or a test overriding settings) rebuilds the service.
    """
    global _service, _service_key
    current = settings or get_settings()
    key = (
        current.llm_provider,
        current.llm_model,
        current.ollama_base_url,
        current.llm_timeout_seconds,
        current.llm_temperature,
        current.llm_num_ctx,
        current.llm_max_tokens,
    )
    if _service is None or _service_key != key:
        _service = build_llm_service(current)
        _service_key = key
    return _service


def reset_llm_service() -> None:
    """Drop the cached service (used by tests and after a settings change)."""
    global _service, _service_key
    _service = None
    _service_key = None