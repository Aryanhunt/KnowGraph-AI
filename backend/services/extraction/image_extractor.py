"""
Image extractor — OCR for JPG/JPEG/PNG/WEBP/TIFF/BMP notes (brief §3).

The image is treated as a single page. The original file path is preserved as the
page image (so the UI can show the exact screenshot the text came from) and the
OCR confidence is stored when the engine reports one.

Small images are upscaled before OCR: screenshots of notes are frequently under
1000 px wide, and Tesseract's accuracy drops sharply at that size. The resize is
documented here because it is a real preprocessing step, not a hidden trick.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from services.extraction.base import DocumentExtractor, ExtractedPage, ExtractionResult
from utils.text import clean_text

logger = logging.getLogger(__name__)

#: Images whose largest side is below this are upscaled before OCR.
MIN_OCR_DIMENSION = 1000
UPSCALE_FACTOR = 2


class ImageExtractor(DocumentExtractor):
    """OCR-based extractor for image notes and scans."""

    source_type = "image"
    extensions = ("png", "jpg", "jpeg", "webp", "tif", "tiff", "bmp")

    def extract(
        self,
        path: Path,
        *,
        document_id: str,
        document_title: str = "",
        page_image_dir: Optional[Path] = None,
    ) -> ExtractionResult:
        result = ExtractionResult(source_type=self.source_type, method="ocr", title=document_title)
        page = ExtractedPage(page_number=1, image_path=str(path))

        width, height = self._dimensions(path)
        if width and height:
            result.metadata = {"width": width, "height": height}

        if not self.ocr_service.is_available():
            message = self.ocr_service.unavailable_reason() or "No OCR engine is available."
            page.warnings.append(message)
            result.warnings.append(f"{message} The image was uploaded and preserved.")
            result.pages = [page]
            return result

        prepared = self._prepare_for_ocr(path)
        preprocess_meta: Dict[str, Any] = {}
        try:
            ocr_result = self.ocr_service.recognize_image(prepared, page_number=1)
        finally:
            # A temporary upscaled/preprocessed copy is only needed during recognition.
            if prepared != path and prepared.exists():
                try:
                    prepared.unlink()
                except OSError:  # pragma: no cover - best effort cleanup
                    pass

        page.text = clean_text(ocr_result.text)
        page.ocr_used = True
        page.ocr_confidence = ocr_result.confidence
        if not ocr_result.ok or not page.has_text:
            message = ocr_result.error or "OCR could not read any text in this image."
            page.warnings.append(message)
            result.warnings.append(message)
        if prepared != path:
            preprocess_meta = {"upscale": f"{UPSCALE_FACTOR}x for OCR"}
            result.metadata["ocr_preprocessing"] = "upscaled for OCR"

        # --- quality assessment ------------------------------------------------
        from services.ocr.quality import assess_quality

        report = assess_quality(
            page.text,
            ocr_result.confidence,
            ocr_used=True,
            ocr_ok=ocr_result.ok,
            engine=ocr_result.engine,
        )
        page.quality_label = report.label
        page.quality_metrics = report.to_dict()["metrics"]
        page.quality_warnings = report.warnings
        page.ocr_engine = ocr_result.engine
        page.ocr_preprocessing = preprocess_meta

        result.pages = [page]
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _dimensions(path: Path) -> tuple:
        try:
            from PIL import Image

            with Image.open(path) as handle:
                return handle.size
        except Exception as exc:  # noqa: BLE001 - unreadable image is reported upstream
            logger.warning("Could not read image dimensions for %s: %s", path.name, exc)
            return (0, 0)

    def _prepare_for_ocr(self, path: Path) -> Path:
        """Return the original path, or a temporary upscaled copy for small images."""
        try:
            from PIL import Image

            with Image.open(path) as handle:
                width, height = handle.size
                if max(width, height) >= MIN_OCR_DIMENSION:
                    return path
                resized = handle.convert("RGB").resize(
                    (width * UPSCALE_FACTOR, height * UPSCALE_FACTOR), Image.LANCZOS
                )
                temp_path = path.with_name(f"{path.stem}__ocr_upscaled.png")
                resized.save(temp_path, format="PNG")
                return temp_path
        except Exception as exc:  # noqa: BLE001 - fall back to the original file
            logger.warning("OCR preprocessing skipped for %s: %s", path.name, exc)
            return path