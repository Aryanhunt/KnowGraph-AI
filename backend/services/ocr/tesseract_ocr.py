"""
Tesseract OCR adapter.

Tesseract is a fully local OCR engine; ``pytesseract`` is only the wrapper that
calls the ``tesseract`` binary, so nothing leaves the machine (brief §23).

Confidence handling: ``image_to_data`` returns a per-word confidence which is
averaged over the words the engine actually recognised. When the engine cannot
report confidence the field stays ``None`` instead of being invented (brief §15
warns against fabricated numbers).
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.ocr.base import OCRResult, OCRService

logger = logging.getLogger(__name__)

#: Page segmentation mode 3 = fully automatic page segmentation (sane default).
DEFAULT_PSM = 3


class TesseractOCRService(OCRService):
    """OCRService implementation backed by the local Tesseract binary."""

    engine = "tesseract"

    def __init__(
        self,
        *,
        lang: str = "eng",
        min_chars_per_page: int = 80,
        tesseract_cmd: str = "",
        psm: int = DEFAULT_PSM,
    ) -> None:
        super().__init__(lang=lang, min_chars_per_page=min_chars_per_page)
        self.psm = psm
        self.tesseract_cmd = tesseract_cmd
        if tesseract_cmd:
            # An explicit path (TESSERACT_CMD) wins over PATH discovery.
            pytesseract = self._import_pytesseract()
            if pytesseract is not None:
                pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------
    @staticmethod
    def _import_pytesseract():
        try:
            import pytesseract

            return pytesseract
        except ImportError:
            return None

    def is_available(self) -> bool:
        pytesseract = self._import_pytesseract()
        if pytesseract is None:
            return False
        if not self.tesseract_cmd and shutil.which("tesseract") is None:
            return False
        try:
            pytesseract.get_tesseract_version()
            return True
        except Exception:  # pragma: no cover - depends on the host binary
            return False

    def unavailable_reason(self) -> str:
        if self._import_pytesseract() is None:
            return "The Python package 'pytesseract' is not installed."
        if not self.tesseract_cmd and shutil.which("tesseract") is None:
            return "The Tesseract binary was not found on PATH. Install it with `brew install tesseract`."
        return "Tesseract could not be started. Check TESSERACT_CMD in backend/.env."

    def version(self) -> Optional[str]:
        pytesseract = self._import_pytesseract()
        if pytesseract is None:
            return None
        try:
            return str(pytesseract.get_tesseract_version())
        except Exception:  # pragma: no cover
            return None

    def describe(self) -> Dict[str, Any]:
        status = super().describe()
        status["version"] = self.version()
        status["psm"] = self.psm
        return status

    # ------------------------------------------------------------------
    # Recognition
    # ------------------------------------------------------------------
    def recognize_image(self, image_path: Path, *, page_number: Optional[int] = None) -> OCRResult:
        started = time.perf_counter()
        pytesseract = self._import_pytesseract()
        if pytesseract is None:
            return OCRResult(engine=self.engine, ok=False, error=self.unavailable_reason())

        path = Path(image_path)
        if not path.exists():
            return OCRResult(engine=self.engine, ok=False, error=f"Image not found: {path.name}")

        try:
            from PIL import Image

            with Image.open(path) as handle:
                # Normalise palette/alpha images so Tesseract receives clean input.
                image = handle.convert("L") if handle.mode in {"P", "RGBA", "LA"} else handle.convert("RGB")
                data = pytesseract.image_to_data(
                    image,
                    lang=self.lang,
                    config=f"--psm {self.psm}",
                    output_type=pytesseract.Output.DICT,
                )
        except Exception as exc:  # noqa: BLE001 - engine errors are reported, never raised
            logger.warning("OCR failed for %s: %s", path.name, exc)
            return OCRResult(engine=self.engine, ok=False, error=f"OCR could not read this page: {exc}")

        text = _text_from_data(data)
        confidence = _mean_confidence(data)
        duration = int((time.perf_counter() - started) * 1000)

        if not text.strip():
            return OCRResult(
                text="",
                confidence=confidence,
                engine=self.engine,
                ok=False,
                error="OCR could not read this page. The page has been preserved and can be reviewed manually.",
                duration_ms=duration,
                metadata={"page_number": page_number},
            )

        return OCRResult(
            text=text,
            confidence=confidence,
            engine=self.engine,
            ok=True,
            duration_ms=duration,
            metadata={"page_number": page_number, "version": self.version()},
        )


# ---------------------------------------------------------------------------
# Helpers for Tesseract's word boxes
# ---------------------------------------------------------------------------
def _text_from_data(data: Dict[str, List[Any]]) -> str:
    """
    Rebuild readable text from ``image_to_data`` output.

    Words are regrouped by (page, block, paragraph, line) so the original reading
    order is preserved — chunking and page citations depend on that order.
    """
    lines: Dict[tuple, List[str]] = {}
    order: List[tuple] = []
    texts = data.get("text") or []
    for index, word in enumerate(texts):
        token = (word or "").strip()
        if not token:
            continue
        key = (
            data.get("page_num", [1] * len(texts))[index],
            data.get("block_num", [0] * len(texts))[index],
            data.get("par_num", [0] * len(texts))[index],
            data.get("line_num", [0] * len(texts))[index],
        )
        if key not in lines:
            lines[key] = []
            order.append(key)
        lines[key].append(token)
    return "\n".join(" ".join(lines[key]) for key in order)


def _mean_confidence(data: Dict[str, List[Any]]) -> Optional[float]:
    """Average word confidence; ``None`` when nothing usable was reported."""
    confidences = data.get("conf") or []
    texts = data.get("text") or []
    values: List[float] = []
    for index, raw in enumerate(confidences):
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        has_text = index < len(texts) and bool((texts[index] or "").strip())
        if value >= 0 and has_text:
            values.append(value)
    if not values:
        return None
    return round(sum(values) / len(values), 1)