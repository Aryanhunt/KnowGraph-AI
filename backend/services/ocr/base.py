"""
OCR abstraction (brief §3).

The rule the whole pipeline depends on: *a scanned page must be handled without
the user saying so*. That decision lives in :func:`needs_ocr` — it is a pure
function of the digital text a page produced and the configured threshold, so it
is trivially testable.

Engines are pluggable: :class:`OCRService` is the contract, Tesseract and
PaddleOCR are the shipped implementations, and ``null_ocr`` keeps the app running
(with a clear message) when no engine is installed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.text import is_meaningful_text, usable_char_count


@dataclass
class OCRResult:
    """Outcome of one OCR pass (one page or one image)."""

    text: str = ""
    confidence: Optional[float] = None      # 0..100 when the engine reports it
    engine: str = ""
    ok: bool = True
    error: Optional[str] = None
    duration_ms: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        return usable_char_count(self.text)


def needs_ocr(text: str, min_chars: int) -> bool:
    """
    Decide whether a page's digital text is good enough to skip OCR.

    A page is treated as scanned when it produced fewer usable characters than
    ``min_chars`` (``OCR_MIN_CHARS_PER_PAGE``). Mixed PDFs therefore work
    page-by-page: digital pages skip OCR, image-only pages go through it.
    """
    return not is_meaningful_text(text, min_chars)


class OCRService(ABC):
    """Contract shared by every OCR engine implementation."""

    engine: str = "unknown"

    def __init__(self, *, lang: str = "eng", min_chars_per_page: int = 80) -> None:
        self.lang = lang
        self.min_chars_per_page = min_chars_per_page

    @abstractmethod
    def recognize_image(self, image_path: Path, *, page_number: Optional[int] = None) -> OCRResult:
        """Run OCR on a single image file (JPG/PNG/WEBP/rendered PDF page)."""

    def recognize_images(self, image_paths: List[Path]) -> List[OCRResult]:
        """
        Run OCR on several images.

        Implementations may override this to reuse a loaded model between pages
        (PaddleOCR does); the default is simply to call
        :meth:`recognize_image` for each image.
        """
        return [self.recognize_image(path) for path in image_paths]

    @abstractmethod
    def is_available(self) -> bool:
        """True when the engine and its binary/model are usable right now."""

    def unavailable_reason(self) -> str:
        """Human readable explanation shown when :meth:`is_available` is False."""
        return f"The {self.engine} OCR engine is not installed or not reachable."

    def describe(self) -> Dict[str, Any]:
        """Status block for ``GET /api/system/health`` and the settings page."""
        available = self.is_available()
        return {
            "engine": self.engine,
            "available": available,
            "language": self.lang,
            "min_chars_per_page": self.min_chars_per_page,
            "reason": None if available else self.unavailable_reason(),
        }