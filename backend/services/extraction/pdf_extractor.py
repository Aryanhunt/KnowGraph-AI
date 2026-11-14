"""
PDF extractor with automatic scanned-page detection (brief §3).

The algorithm, per page — exactly as the brief describes:

1. try normal digital text extraction (PyMuPDF),
2. if the page yields fewer usable characters than ``OCR_MIN_CHARS_PER_PAGE``,
   treat that page as scanned,
3. render the page to a PNG (PyMuPDF does this natively, so no Poppler binary
   is required),
4. run the configured local OCR engine on the render,
5. keep both the recognised text and the page image path.

Because the decision is made per page, mixed PDFs work out of the box:

    document.pdf
     ├── page 1 → digital text
     ├── page 2 → OCR
     ├── page 3 → OCR
     └── page 4 → digital text

Pages that fail OCR are preserved (image + warning) instead of aborting the
upload, which is what brief §22 asks for.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Tuple

from services.extraction.base import DocumentExtractor, ExtractedPage, ExtractionResult
from services.ocr.base import OCRResult, needs_ocr
from utils.text import clean_text

logger = logging.getLogger(__name__)

#: Safety valve so a pathological file cannot occupy the worker forever.
MAX_PAGES = 800


class PdfExtractor(DocumentExtractor):
    """PDF extractor: digital text first, OCR only where it is needed."""

    source_type = "pdf"
    extensions = ("pdf",)

    def __init__(self, *, ocr_service, min_chars_per_page: int = 80, render_zoom: float = 2.0) -> None:
        super().__init__(ocr_service=ocr_service, min_chars_per_page=min_chars_per_page)
        self.render_zoom = max(1.0, render_zoom)

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _digital_text(page) -> str:
        """
        Extract digital text from a PyMuPDF page.

        ``sort=True`` keeps the visual reading order, which matters for chunking
        quality in two-column layouts.
        """
        try:
            text = page.get_text("text", sort=True)
        except TypeError:  # pragma: no cover - older PyMuPDF signature
            text = page.get_text("text")
        return text or ""

    def _render_page(
        self,
        page,
        *,
        page_number: int,
        page_image_dir: Optional[Path],
        document_id: str,
    ) -> Optional[Path]:
        """Rasterise one page to PNG and return the stored path."""
        if page_image_dir is None:
            return None
        target_dir = Path(page_image_dir) / str(document_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"page-{page_number:04d}.png"
        if target.exists():
            return target
        try:
            import fitz  # PyMuPDF

            matrix = fitz.Matrix(self.render_zoom, self.render_zoom)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            pixmap.save(str(target))
            return target
        except Exception as exc:  # noqa: BLE001 - rendering failures are reported
            logger.warning("Could not render page %s: %s", page_number, exc)
            return None

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def extract(
        self,
        path: Path,
        *,
        document_id: str,
        document_title: str = "",
        page_image_dir: Optional[Path] = None,
    ) -> ExtractionResult:
        """Extract every page, running OCR only on the pages that need it."""
        result = ExtractionResult(source_type=self.source_type, method="digital_text",
                                  title=document_title)
        try:
            import fitz  # PyMuPDF
        except ImportError:
            result.warnings.append("PyMuPDF is not installed, so PDF text cannot be extracted.")
            return result

        try:
            document = fitz.open(str(path))
        except Exception as exc:  # noqa: BLE001 - corrupt or password protected PDF
            result.warnings.append(
                f"This PDF could not be opened ({exc}). The file may be corrupted or protected."
            )
            return result

        try:
            if document.is_encrypted:
                # An empty password covers the common "owner password only" case.
                if not document.authenticate(""):
                    result.warnings.append("This PDF is password protected and could not be read.")
                    return result

            metadata = document.metadata or {}
            if not result.title and metadata.get("title"):
                result.title = str(metadata["title"]).strip()
            result.metadata = {
                "pdf_page_count": int(document.page_count),
                "pdf_author": (metadata.get("author") or "").strip(),
                "pdf_subject": (metadata.get("subject") or "").strip(),
                "pdf_producer": (metadata.get("producer") or "").strip(),
            }

            if document.page_count > MAX_PAGES:
                result.warnings.append(
                    f"Only the first {MAX_PAGES} pages of {document.page_count} were processed."
                )

            pages: List[ExtractedPage] = []
            ocr_queue: List[Tuple[int, Path]] = []      # (page index, rendered image)

            # --- pass 1: digital text, decide per page whether OCR is needed --
            for position in range(min(document.page_count, MAX_PAGES)):
                page = document.load_page(position)
                page_number = position + 1
                digital = clean_text(self._digital_text(page))
                extracted = ExtractedPage(page_number=page_number, text=digital)

                if needs_ocr(digital, self.min_chars_per_page):
                    if self.ocr_service.is_available():
                        image_path = self._render_page(
                            page,
                            page_number=page_number,
                            page_image_dir=page_image_dir,
                            document_id=document_id,
                        )
                        extracted.image_path = str(image_path) if image_path else None
                        if image_path is not None:
                            ocr_queue.append((len(pages), image_path))
                    else:
                        extracted.warnings.append(
                            self.ocr_service.unavailable_reason()
                            or "This page appears to be scanned but no OCR engine is available."
                        )
                pages.append(extracted)

            # --- pass 2: OCR the scanned pages in one batch ------------------
            if ocr_queue:
                ocr_results = self.ocr_service.recognize_images([item[1] for item in ocr_queue])
                for (page_index, image_path), ocr_result in zip(ocr_queue, ocr_results):
                    self._apply_ocr(pages[page_index], ocr_result, image_path, result)

            result.pages = pages

            # --- record which extraction method was actually used -----------
            methods = {
                "ocr" if page.ocr_used else "digital"
                for page in pages
                if page.has_text or page.ocr_used
            }
            if methods == {"ocr"}:
                result.method = "ocr"
            elif methods == {"digital"}:
                result.method = "digital_text"
            elif methods:
                result.method = "mixed"

            if not result.has_content:
                result.warnings.append(
                    "No readable text could be extracted from this PDF. "
                    "The file and its page images have been preserved."
                )
            return result
        finally:
            document.close()

    @staticmethod
    def _apply_ocr(
        page: ExtractedPage,
        ocr_result: OCRResult,
        image_path: Path,
        result: ExtractionResult,
    ) -> None:
        """Copy OCR output onto the page, keeping the page image as evidence."""
        from services.ocr.quality import assess_quality

        cleaned = clean_text(ocr_result.text)
        if cleaned.strip():
            page.text = cleaned
            page.ocr_used = True
            page.ocr_confidence = ocr_result.confidence
            page.image_path = str(image_path)
        else:
            page.ocr_used = True           # OCR *was* attempted on this page
            page.ocr_confidence = ocr_result.confidence
            page.image_path = str(image_path)
            message = ocr_result.error or "OCR could not read this page."
            page.warnings.append(message)
            if message not in result.warnings:
                result.warnings.append(message)

        # --- quality assessment (always, success or failure) -----------------
        report = assess_quality(
            cleaned,
            ocr_result.confidence,
            ocr_used=True,
            ocr_ok=ocr_result.ok,
            engine=ocr_result.engine,
        )
        page.quality_label = report.label
        page.quality_metrics = report.to_dict()["metrics"]
        page.quality_warnings = report.warnings
        page.ocr_engine = ocr_result.engine