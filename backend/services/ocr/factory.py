"""
OCR factory.

Chooses the engine named by ``OCR_ENGINE`` in ``backend/.env`` (brief §2).

Graceful degradation: if the configured engine is installed-but-unavailable
(e.g. the Tesseract binary is missing), the factory returns a
:class:`~services.ocr.null_ocr.NullOCRService` carrying the real reason. Uploads
then still succeed, the page image is preserved, and the UI explains what to
install — instead of the request failing with a stack trace (brief §22).
"""

from __future__ import annotations

from typing import Dict, Optional, Type

from config.settings import Settings, get_settings
from services.ocr.base import OCRService
from services.ocr.null_ocr import NullOCRService
from services.ocr.paddle_ocr import PaddleOCRService
from services.ocr.tesseract_ocr import TesseractOCRService
from utils.errors import ConfigurationError
from utils.logging_setup import get_logger

logger = get_logger(__name__)

#: Supported engines. Add a class here to support another local OCR engine.
ENGINES: Dict[str, Type[OCRService]] = {
    "tesseract": TesseractOCRService,
    "paddleocr": PaddleOCRService,
    "none": NullOCRService,
}

_service: Optional[OCRService] = None
_service_key: Optional[tuple] = None


def build_ocr_service(settings: Optional[Settings] = None) -> OCRService:
    """Create a new OCR service instance without caching."""
    current = settings or get_settings()
    engine = (current.ocr_engine or "tesseract").lower()

    if not current.ocr_enabled:
        return NullOCRService("OCR is disabled (OCR_ENABLED=false in backend/.env).")
    if engine not in ENGINES:
        raise ConfigurationError(
            f"Unknown OCR_ENGINE '{engine}'.",
            hint=f"Supported engines: {', '.join(sorted(ENGINES))}.",
        )

    if engine == "none":
        return NullOCRService("No OCR engine is configured (OCR_ENGINE=none).")

    if engine == "paddleocr":
        service: OCRService = PaddleOCRService(
            lang=current.ocr_lang, min_chars_per_page=current.ocr_min_chars_per_page
        )
    else:
        service = TesseractOCRService(
            lang=current.ocr_lang,
            min_chars_per_page=current.ocr_min_chars_per_page,
            tesseract_cmd=current.tesseract_cmd,
        )

    if not service.is_available():
        reason = service.unavailable_reason()
        logger.warning("OCR engine '%s' is unavailable: %s", engine, reason)
        return NullOCRService(reason)
    return service


def get_ocr_service(settings: Optional[Settings] = None) -> OCRService:
    """Cached OCR service, rebuilt when the configuration changes."""
    global _service, _service_key
    current = settings or get_settings()
    key = (
        current.ocr_engine,
        current.ocr_enabled,
        current.ocr_lang,
        current.ocr_min_chars_per_page,
        current.tesseract_cmd,
    )
    if _service is None or _service_key != key:
        _service = build_ocr_service(current)
        _service_key = key
        logger.info("OCR engine ready: %s", _service.describe())
    return _service


def reset_ocr_service() -> None:
    """Drop the cached service (used by tests and after a settings change)."""
    global _service, _service_key
    _service = None
    _service_key = None