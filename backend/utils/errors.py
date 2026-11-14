"""
Application error taxonomy.

Every failure that can reach the user is expressed as an ``AppError`` subclass so
that ``app.py`` can turn it into a predictable JSON payload:

    {"error": {"code": "ollama_unavailable",
               "message": "Ollama is not running.",
               "hint": "Please start Ollama ..."}}

The brief (§22) requires that a failed OCR pass, a missing Ollama server, a
corrupt PDF, a dead vector database or an empty extraction never crash the API —
they must produce an actionable message instead. The helpers at the bottom of
this module exist for exactly that purpose.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for all expected (i.e. non-bug) failures."""

    status_code: int = 500
    code: str = "internal_error"
    default_message: str = "Something went wrong while processing the request."

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        code: Optional[str] = None,
        status_code: Optional[int] = None,
        hint: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.message = message or self.default_message
        self.hint = hint
        self.details = details or {}
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.hint:
            payload["hint"] = self.hint
        if self.details:
            payload["details"] = self.details
        return {"error": payload}


# ---------------------------------------------------------------------------
# Client errors (4xx)
# ---------------------------------------------------------------------------
class ValidationError(AppError):
    status_code = 400
    code = "validation_error"
    default_message = "The request payload is invalid."


class AuthError(AppError):
    status_code = 401
    code = "unauthorized"
    default_message = "Authentication is required."


class AccessDeniedError(AppError):
    status_code = 403
    code = "forbidden"
    default_message = "You do not have access to this resource."


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    default_message = "The requested resource was not found."


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    default_message = "The resource already exists."


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"
    default_message = "The uploaded file is too large."


class UnsupportedFileTypeError(ValidationError):
    status_code = 415
    code = "unsupported_file_type"
    default_message = "This file type is not supported."


class ProcessingError(AppError):
    """A document could not be processed (corrupt PDF, no readable text, ...)."""

    status_code = 422
    code = "processing_error"
    default_message = "The document could not be processed."


# ---------------------------------------------------------------------------
# Server / dependency errors (5xx)
# ---------------------------------------------------------------------------
class ConfigurationError(AppError):
    status_code = 500
    code = "configuration_error"
    default_message = "The server is misconfigured."


class DatabaseError(AppError):
    status_code = 503
    code = "database_unavailable"
    default_message = "The metadata database is unavailable."


class LocalServiceUnavailableError(AppError):
    """A *local* dependency (Ollama, Chroma, Tesseract) is not reachable."""

    status_code = 503
    code = "local_service_unavailable"
    default_message = "A required local service is not available."


# ---------------------------------------------------------------------------
# Ready-made local-service failures carrying user-facing guidance
# ---------------------------------------------------------------------------
def ollama_unavailable(model: str = "", base_url: str = "") -> LocalServiceUnavailableError:
    target = f" at {base_url}" if base_url else ""
    wanted = f" and run `ollama pull {model}`" if model else ""
    return LocalServiceUnavailableError(
        f"Ollama is not running{target}.",
        code="ollama_unavailable",
        hint=f"Please start Ollama (`ollama serve`){wanted}, then try again.",
        details={"model": model, "base_url": base_url},
    )


def ollama_model_missing(model: str) -> LocalServiceUnavailableError:
    return LocalServiceUnavailableError(
        f"The Ollama model '{model}' is not installed.",
        code="ollama_model_missing",
        hint=f"Run `ollama pull {model}` (or change the model in backend/.env).",
        details={"model": model},
    )


def vector_store_unavailable(reason: str = "") -> LocalServiceUnavailableError:
    return LocalServiceUnavailableError(
        "The local vector database is unavailable.",
        code="vector_store_unavailable",
        hint="Check VECTOR_DB in backend/.env and the storage/vectorstore directory.",
        details={"reason": reason} if reason else None,
    )


def ocr_unavailable(reason: str = "") -> LocalServiceUnavailableError:
    return LocalServiceUnavailableError(
        "The local OCR engine is not available.",
        code="ocr_unavailable",
        hint="Install Tesseract (`brew install tesseract`) or change OCR_ENGINE in backend/.env.",
        details={"reason": reason} if reason else None,
    )


def database_unavailable(reason: str = "") -> DatabaseError:
    return DatabaseError(
        "Cannot reach MongoDB.",
        code="database_unavailable",
        hint="Start MongoDB (`brew services start mongodb-community`) and verify MONGO_URI.",
        details={"reason": reason} if reason else None,
    )


# ---------------------------------------------------------------------------
# Flask integration
# ---------------------------------------------------------------------------
def install_error_handlers(app) -> None:
    """Register JSON error handlers so the API never returns an HTML crash page."""
    from werkzeug.exceptions import HTTPException

    @app.errorhandler(AppError)
    def _handle_app_error(error: AppError):  # pragma: no cover - thin wrapper
        level = logging.ERROR if error.status_code >= 500 else logging.INFO
        logger.log(level, "%s: %s", error.code, error.message)
        status = error.status_code
        return error.to_dict(), status

    @app.errorhandler(HTTPException)
    def _handle_http_error(error: HTTPException):  # pragma: no cover - thin wrapper
        return (
            {
                "error": {
                    "code": (error.name or "http_error").lower().replace(" ", "_"),
                    "message": error.description or "Request failed.",
                }
            },
            error.code or 500,
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(error: Exception):  # pragma: no cover - safety net
        logger.exception("Unhandled exception: %s", error)
        return (
            {
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected server error occurred.",
                    "hint": "See backend/logs/app.log for the full traceback.",
                }
            },
            500,
        )