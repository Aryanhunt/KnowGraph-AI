"""
PaddleOCR adapter (optional engine).

Kept as a genuinely working second implementation so the abstraction in
``services/ocr/base.py`` is proven replaceable (brief §3 allows PaddleOCR *or*
Tesseract). PaddleOCR is not a default dependency because it pulls in the
PaddlePaddle runtime (~1 GB); install it and set ``OCR_ENGINE=paddleocr`` in
``backend/.env`` to switch.

The import is guarded so a missing PaddlePaddle installation degrades to
"unavailable" instead of breaking the application.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.ocr.base import OCRResult, OCRService

logger = logging.getLogger(__name__)


class PaddleOCRService(OCRService):
    """OCRService implementation backed by PaddleOCR (local model, no network)."""

    engine = "paddleocr"

    def __init__(self, *, lang: str = "en", min_chars_per_page: int = 80, use_gpu: bool = False) -> None:
        super().__init__(lang=lang, min_chars_per_page=min_chars_per_page)
        self.use_gpu = use_gpu
        self._engine = None
        self._load_error: Optional[str] = None

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------
    def _load(self):
        """Load the model once and reuse it for every page (it is expensive)."""
        if self._engine is not None or self._load_error is not None:
            return self._engine
        try:
            from paddleocr import PaddleOCR  # type: ignore
        except ImportError:
            self._load_error = (
                "PaddleOCR is not installed. Install it with "
                "`pip install paddleocr paddlepaddle`, or set OCR_ENGINE=tesseract in backend/.env."
            )
            return None
        try:
            try:
                # Older releases accept these flags.
                self._engine = PaddleOCR(
                    use_angle_cls=True, lang=self.lang, show_log=False, use_gpu=self.use_gpu
                )
            except TypeError:
                # Newer releases removed them from the constructor.
                self._engine = PaddleOCR(lang=self.lang)
        except Exception as exc:  # noqa: BLE001 - model initialisation can fail
            self._load_error = f"PaddleOCR could not be initialised: {exc}"
            logger.warning(self._load_error)
            return None
        return self._engine

    def is_available(self) -> bool:
        return self._load() is not None

    def unavailable_reason(self) -> str:
        self._load()
        return self._load_error or "PaddleOCR is not available."

    def describe(self) -> Dict[str, Any]:
        status = super().describe()
        status["use_gpu"] = self.use_gpu
        return status

    # ------------------------------------------------------------------
    # Recognition
    # ------------------------------------------------------------------
    def recognize_image(self, image_path: Path, *, page_number: Optional[int] = None) -> OCRResult:
        result = self.recognize_images([image_path])[0]
        result.metadata["page_number"] = page_number
        return result

    def recognize_images(self, image_paths: List[Path]) -> List[OCRResult]:
        """Batch call — the model stays loaded between pages."""
        engine = self._load()
        if engine is None:
            reason = self.unavailable_reason()
            return [
                OCRResult(engine=self.engine, ok=False, error=reason, metadata={"image_path": str(path)})
                for path in image_paths
            ]

        outputs: List[OCRResult] = []
        for path in image_paths:
            started = time.perf_counter()
            try:
                raw = engine.ocr(str(path))
            except Exception as exc:  # noqa: BLE001 - report, never raise
                outputs.append(
                    OCRResult(
                        engine=self.engine,
                        ok=False,
                        error=f"OCR could not read this page: {exc}",
                        metadata={"image_path": str(path)},
                    )
                )
                continue

            text, confidence = _parse_paddle_result(raw)
            outputs.append(
                OCRResult(
                    text=text,
                    confidence=confidence,
                    engine=self.engine,
                    ok=bool(text.strip()),
                    error=None if text.strip() else "OCR could not read this page.",
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    metadata={"image_path": str(path)},
                )
            )
        return outputs


def _parse_paddle_result(raw: Any) -> tuple:
    """
    Normalise PaddleOCR output across versions.

    ``paddleocr`` 2.x returns ``[[[box, (text, score)], ...]]`` while 3.x returns
    ``[{"rec_texts": [...], "rec_scores": [...]}]``. Both shapes are handled.
    """
    lines: List[str] = []
    scores: List[float] = []

    def consume(entry: Any) -> None:
        if isinstance(entry, dict):
            texts = entry.get("rec_texts") or []
            line_scores = entry.get("rec_scores") or []
            for index, text in enumerate(texts):
                if not text:
                    continue
                lines.append(str(text))
                if index < len(line_scores):
                    try:
                        scores.append(float(line_scores[index]))
                    except (TypeError, ValueError):
                        pass
            return
        if isinstance(entry, (list, tuple)) and len(entry) == 2:
            payload = entry[1]
            if isinstance(payload, (list, tuple)) and payload:
                lines.append(str(payload[0]))
                if len(payload) > 1:
                    try:
                        scores.append(float(payload[1]))
                    except (TypeError, ValueError):
                        pass

    for item in raw or []:
        # 2.x wraps one image's lines in an extra list level.
        if isinstance(item, list) and item and not isinstance(item[0], (str, bytes)):
            for entry in item:
                consume(entry)
        else:
            consume(item)

    confidence = round(100 * sum(scores) / len(scores), 1) if scores else None
    return "\n".join(lines).strip(), confidence