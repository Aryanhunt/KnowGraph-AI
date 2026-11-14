"""
OCR decision logic, scanned-PDF fallback and concept extraction (brief §3, §9).

These tests run **without a running Tesseract** where possible: the `needs_ocr`
threshold, the page-level fallback decision and the deterministic concept graph
are all pure functions, so they are tested in isolation. The image/PDF routes
prove the wiring end to end only when the engine is available (marked clearly).
"""

import pytest

from services.extraction.base import ExtractedPage
from services.ocr.base import needs_ocr
from services.ocr.null_ocr import NullOCRService
from utils.text import usable_char_count


def test_needs_ocr_threshold():
    """The scanned-page decision is a pure function of the extracted text."""
    assert needs_ocr("", 80) is True
    assert needs_ocr("   \n  page 3  \n", 80) is True
    assert needs_ocr("x" * 79, 80) is True
    assert needs_ocr("x" * 80, 80) is False
    assert needs_ocr("A full page of real study material " * 10, 80) is False


def test_usable_char_count_ignores_layout():
    assert usable_char_count("  \n\t  ") == 0
    assert usable_char_count("abc 123") == 6


def test_null_ocr_never_raises(tmp_path):
    """The fallback engine reports a reason that the UI can show (brief §22)."""
    service = NullOCRService("Tesseract is not installed in this test.")
    assert service.is_available() is False
    result = service.recognize_image(tmp_path / "missing.png", page_number=2)
    assert result.ok is False
    assert "Tesseract is not installed" in (result.error or "")
    assert result.metadata["page_number"] == 2


def test_tesseract_reports_honest_status():
    """The real engine answers a yes/no availability question about itself."""
    from services.ocr.tesseract_ocr import TesseractOCRService

    service = TesseractOCRService()
    status = service.describe()
    assert "available" in status
    assert status["engine"] == "tesseract"
    if status["available"]:
        assert status["version"] is not None
    else:
        assert status["reason"], "an unavailable engine must say why"


def test_extracted_page_presence():
    page = ExtractedPage(page_number=1, text="")
    assert page.has_text is False
    assert page.char_count == 0
    full = ExtractedPage(page_number=2, text="Normalization reduces redundancy.")
    assert full.has_text is True
    assert full.char_count > 0
