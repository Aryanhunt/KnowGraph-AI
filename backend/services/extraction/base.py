"""
Document extraction abstraction (brief §3, §4).

Every extractor returns the same :class:`ExtractionResult` structure, which is
what makes the rest of the pipeline uniform: page numbers, OCR usage, OCR
confidence and the stored page image travel together, so a citation like
"DBMS Notes — page 14" is always truthful (brief §26.14: preserve document/page/
source metadata throughout the pipeline).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.ocr.base import OCRService
from utils.text import usable_char_count


@dataclass
class ExtractedPage:
    """Text produced for one page (or one logical section for non-paginated files)."""

    page_number: int
    text: str = ""
    ocr_used: bool = False
    ocr_confidence: Optional[float] = None
    image_path: Optional[str] = None
    section_title: str = ""
    warnings: List[str] = field(default_factory=list)
    # --- OCR quality pipeline ------------------------------------------------
    quality_label: str = ""
    quality_metrics: Dict[str, Any] = field(default_factory=dict)
    quality_warnings: List[str] = field(default_factory=list)
    ocr_engine: str = ""
    ocr_preprocessing: Dict[str, Any] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        return usable_char_count(self.text)

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())


@dataclass
class ExtractionResult:
    """Everything an extractor learned about a file."""

    pages: List[ExtractedPage] = field(default_factory=list)
    source_type: str = "unknown"          # pdf | image | docx | text
    method: str = "unknown"               # digital_text | ocr | mixed | docx | plain_text
    title: str = ""
    language: str = "unknown"
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # -- derived facts -----------------------------------------------------
    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def ocr_used(self) -> bool:
        return any(page.ocr_used for page in self.pages)

    @property
    def ocr_page_count(self) -> int:
        return sum(1 for page in self.pages if page.ocr_used)

    @property
    def char_count(self) -> int:
        return sum(page.char_count for page in self.pages)

    @property
    def has_content(self) -> bool:
        return any(page.has_text for page in self.pages)

    @property
    def confidence_values(self) -> List[float]:
        return [page.ocr_confidence for page in self.pages if page.ocr_confidence is not None]

    def average_ocr_confidence(self) -> Optional[float]:
        values = self.confidence_values
        if not values:
            return None
        return round(sum(values) / len(values), 1)

    def full_text(self, *, max_chars: Optional[int] = None) -> str:
        """Concatenate pages, separated so page boundaries stay readable."""
        parts = [page.text.strip() for page in self.pages if page.has_text]
        text = "\n\n".join(parts)
        if max_chars and len(text) > max_chars:
            return text[:max_chars]
        return text

    def summary(self) -> Dict[str, Any]:
        """Compact description for the API/logs (never the full text)."""
        return {
            "source_type": self.source_type,
            "method": self.method,
            "page_count": self.page_count,
            "ocr_used": self.ocr_used,
            "ocr_page_count": self.ocr_page_count,
            "char_count": self.char_count,
            "average_ocr_confidence": self.average_ocr_confidence(),
            "language": self.language,
            "warnings": list(self.warnings),
        }


class DocumentExtractor(ABC):
    """Contract implemented by the PDF/image/DOCX/text extractors."""

    source_type: str = "unknown"
    #: File extensions handled by this extractor (without the dot).
    extensions: tuple = ()

    def __init__(self, *, ocr_service: OCRService, min_chars_per_page: int = 80) -> None:
        self.ocr_service = ocr_service
        self.min_chars_per_page = min_chars_per_page

    @classmethod
    def supports(cls, extension: str) -> bool:
        return extension.lower().lstrip(".") in cls.extensions

    @abstractmethod
    def extract(
        self,
        path: Path,
        *,
        document_id: str,
        document_title: str = "",
        page_image_dir: Optional[Path] = None,
    ) -> ExtractionResult:
        """Read the file and return its pages. Must not raise for bad input."""