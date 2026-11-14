"""
Extractor registry.

Maps a file extension to the extractor that handles it, so the pipeline asks one
function (``get_extractor``) instead of knowing about individual formats. Adding
a format means adding one class to :data:`EXTRACTOR_CLASSES` (brief §26.8).
"""

from __future__ import annotations

from typing import Dict, Optional, Type

from config.settings import Settings, get_settings
from services.extraction.base import DocumentExtractor
from services.extraction.docx_extractor import DocxExtractor
from services.extraction.image_extractor import ImageExtractor
from services.extraction.pdf_extractor import PdfExtractor
from services.extraction.text_extractor import TextExtractor
from services.ocr.base import OCRService
from services.ocr.factory import get_ocr_service
from utils.errors import UnsupportedFileTypeError

#: Order matters only for documentation; lookup is by extension.
EXTRACTOR_CLASSES: tuple = (PdfExtractor, ImageExtractor, DocxExtractor, TextExtractor)


def build_extension_map() -> Dict[str, Type[DocumentExtractor]]:
    mapping: Dict[str, Type[DocumentExtractor]] = {}
    for extractor_cls in EXTRACTOR_CLASSES:
        for extension in extractor_cls.extensions:
            mapping[extension] = extractor_cls
    return mapping


EXTENSION_MAP: Dict[str, Type[DocumentExtractor]] = build_extension_map()


def supported_extensions() -> tuple:
    return tuple(sorted(EXTENSION_MAP))


def get_extractor(
    extension: str,
    *,
    ocr_service: Optional[OCRService] = None,
    settings: Optional[Settings] = None,
) -> DocumentExtractor:
    """
    Return a ready-to-use extractor for ``extension``.

    Raises :class:`UnsupportedFileTypeError` when no extractor is registered, with
    the supported list in the hint so the UI can show it directly.
    """
    current = settings or get_settings()
    normalised = (extension or "").lower().lstrip(".")
    extractor_cls = EXTENSION_MAP.get(normalised)
    if extractor_cls is None:
        raise UnsupportedFileTypeError(
            f".{normalised} files are not supported.",
            hint=f"Supported types: {', '.join(supported_extensions())}",
        )

    ocr = ocr_service or get_ocr_service(current)

    if extractor_cls is PdfExtractor:
        return PdfExtractor(
            ocr_service=ocr,
            min_chars_per_page=current.ocr_min_chars_per_page,
            render_zoom=current.pdf_render_zoom,
        )
    return extractor_cls(ocr_service=ocr, min_chars_per_page=current.ocr_min_chars_per_page)