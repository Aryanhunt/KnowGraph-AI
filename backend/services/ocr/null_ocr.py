"""
Fallback OCR service used when no engine is available.

It keeps the application running instead of crashing on upload: the page is
stored, the document is marked as "OCR unavailable" and the UI shows a clear,
actionable message. This is the graceful-degradation path required by brief §22.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from services.ocr.base import OCRResult, OCRService


class NullOCRService(OCRService):
    """OCRService that always reports a reason instead of recognising text."""

    engine = "none"

    def __init__(self, reason: str = "No OCR engine is configured.", *, lang: str = "eng",
                 min_chars_per_page: int = 80) -> None:
        super().__init__(lang=lang, min_chars_per_page=min_chars_per_page)
        self.reason = reason

    def is_available(self) -> bool:
        return False

    def unavailable_reason(self) -> str:
        return self.reason

    def describe(self) -> Dict[str, Any]:
        status = super().describe()
        status["engine"] = self.engine
        return status

    def recognize_image(self, image_path: Path, *, page_number: Optional[int] = None) -> OCRResult:
        # The message is shown verbatim in the UI (brief §22).
        return OCRResult(
            text="",
            engine=self.engine,
            ok=False,
            error=(
                f"{self.reason} The page image has been preserved and can be reviewed manually."
            ),
            metadata={"page_number": page_number, "image_path": str(image_path)},
        )