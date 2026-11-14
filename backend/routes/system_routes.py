"""
System routes (``/api/system``).

Health and configuration introspection. These endpoints are what make the
"local-first" behaviour visible and debuggable in the UI:

* is MongoDB reachable?
* is Ollama running, and are the configured models installed?
* which OCR engine is active (or why it is not)?
* which vector database is in use and how many vectors it holds?
* how many background jobs are running?
* which file types and AI models are configured?

No secret (``SECRET_KEY`` or a credentialed connection string) is ever returned.
"""

from __future__ import annotations

from flask import Blueprint

from config.settings import get_settings
from services.jobs import get_job_queue
from utils.auth_middleware import optional_user
from utils.files import SUPPORTED_EXTENSIONS
from utils.responses import ok

bp = Blueprint("system", __name__, url_prefix="/api/system")


@bp.get("/health")
def health():
    """
    Aggregate status of every local dependency.

    Each probe is wrapped so a broken dependency produces ``available: false``
    plus a reason instead of a 500 (brief §22).
    """
    settings = get_settings()
    report = {"app_env": settings.app_env}

    try:
        from db.mongo import get_mongo

        manager = get_mongo()
        reachable = manager.ping()
        report["database"] = {
            "available": reachable,
            "name": manager.db_name,
            "reason": None if reachable else "MongoDB is not reachable.",
        }
    except Exception as exc:  # noqa: BLE001
        report["database"] = {"available": False, "reason": str(exc)}

    try:
        from services.llm.factory import get_llm_service

        llm_health = get_llm_service(settings).health()
        report["llm"] = {
            **llm_health,
            "hint": None
            if llm_health.get("available") and llm_health.get("model_installed")
            else f"Start Ollama and run `ollama pull {settings.llm_model}`.",
        }
    except Exception as exc:  # noqa: BLE001
        report["llm"] = {"available": False, "provider": settings.llm_provider, "reason": str(exc)}

    try:
        from services.embeddings.factory import get_embedding_service

        report["embeddings"] = get_embedding_service(settings).describe()
    except Exception as exc:  # noqa: BLE001
        report["embeddings"] = {"available": False, "reason": str(exc)}

    try:
        from services.ocr.factory import get_ocr_service

        report["ocr"] = get_ocr_service(settings).describe()
    except Exception as exc:  # noqa: BLE001
        report["ocr"] = {"engine": settings.ocr_engine, "available": False, "reason": str(exc)}

    try:
        from services.vector.factory import vector_store_status

        report["vector_store"] = vector_store_status(settings)
    except Exception as exc:  # noqa: BLE001
        report["vector_store"] = {"available": False, "reason": str(exc)}

    try:
        report["processing"] = get_job_queue(settings).stats()
    except Exception as exc:  # noqa: BLE001
        report["processing"] = {"available": False, "reason": str(exc)}

    report["ok"] = all(
        bool(report.get(section, {}).get("available"))
        for section in ("database", "llm", "embeddings", "ocr", "vector_store")
    )
    return ok(report)


@bp.get("/config")
def config():
    """The active configuration (models, engines, limits, chunking) — no secrets."""
    settings = get_settings()
    return ok(
        {
            "app_env": settings.app_env,
            "llm": {"provider": settings.llm_provider, "model": settings.llm_model},
            "embeddings": {
                "provider": settings.embedding_provider,
                "model": settings.embedding_model,
            },
            "ocr": {
                "engine": settings.ocr_engine,
                "enabled": settings.ocr_enabled,
                "language": settings.ocr_lang,
                "min_chars_per_page": settings.ocr_min_chars_per_page,
                "pdf_render_zoom": settings.pdf_render_zoom,
            },
            "vector_db": {"backend": settings.vector_db, "collection": settings.chroma_collection},
            "chunking": {"chunk_size": settings.chunk_size, "chunk_overlap": settings.chunk_overlap},
            "retrieval": {
                "top_k": settings.rag_top_k,
                "hybrid": settings.hybrid_search,
                "max_context_chars": settings.rag_max_context_chars,
                "history_turns": settings.rag_history_turns,
            },
            "limits": {"max_upload_mb": settings.max_upload_mb},
            "processing": {"workers": settings.processing_workers, "sync": settings.processing_sync},
            "supported_types": list(SUPPORTED_EXTENSIONS),
            "local_only": True,
        }
    )


@bp.get("/supported-types")
def supported_types():
    """File extensions the uploader accepts (drives drop-zone validation)."""
    return ok(
        [{"extension": extension, "label": f".{extension}"} for extension in SUPPORTED_EXTENSIONS]
    )


@bp.get("/session")
def session():
    """Report whether the caller's token is valid (used by the app boot sequence)."""
    user = optional_user()
    return ok(
        {
            "authenticated": user is not None,
            "user": None
            if user is None
            else {
                "id": str(user["_id"]),
                "email": user.get("email_display", ""),
                "full_name": user.get("full_name", ""),
            },
        }
    )
