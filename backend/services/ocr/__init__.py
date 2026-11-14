"""OCR services (pluggable engines, fully local)."""

from services.ocr.base import OCRResult, OCRService, needs_ocr
from services.ocr.factory import (
    ENGINES,
    build_ocr_service,
    get_ocr_service,
    reset_ocr_service,
)

__all__ = [
    "OCRResult",
    "OCRService",
    "needs_ocr",
    "ENGINES",
    "build_ocr_service",
    "get_ocr_service",
    "reset_ocr_service",
]