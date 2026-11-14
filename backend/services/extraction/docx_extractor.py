"""
DOCX extractor (read-only, never executed — brief §21).

DOCX files have no fixed pages (pagination is decided by the word processor when
the file is opened), so the extractor groups content by heading into sections and
reports section numbers as "pages". That keeps citations meaningful without
inventing page numbers, and the UI labels them as sections.

Paragraphs and tables are both read, because study notes habitually put key
comparisons into tables.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from services.extraction.base import DocumentExtractor, ExtractedPage, ExtractionResult
from utils.text import clean_text, first_heading

logger = logging.getLogger(__name__)


class DocxExtractor(DocumentExtractor):
    """Extractor for Microsoft Word ``.docx`` documents."""

    source_type = "docx"
    extensions = ("docx",)

    def extract(
        self,
        path: Path,
        *,
        document_id: str,
        document_title: str = "",
        page_image_dir: Optional[Path] = None,
    ) -> ExtractionResult:
        result = ExtractionResult(source_type=self.source_type, method="docx", title=document_title)
        try:
            import docx  # python-docx
            from docx.opc.exceptions import PackageNotFoundError
        except ImportError:
            result.warnings.append("python-docx is not installed, so .docx files cannot be read.")
            return result

        try:
            document = docx.Document(str(path))
        except PackageNotFoundError as exc:
            result.warnings.append(f"This .docx file is not a valid Word document ({exc}).")
            return result
        except Exception as exc:  # noqa: BLE001 - corrupt archive, wrong format, ...
            result.warnings.append(f"This .docx file could not be read ({exc}).")
            return result

        blocks = self._iter_blocks(document)

        # Group blocks into sections: a heading starts a new section.
        sections: List[tuple] = []
        current_title = ""
        buffer: List[str] = []
        for style, text in blocks:
            is_heading = style.lower().startswith("heading") or style.lower() == "title"
            if is_heading:
                if buffer and any(item.strip() for item in buffer):
                    sections.append((current_title, "\n".join(buffer)))
                current_title = text.strip()
                buffer = [text.strip()]
            else:
                buffer.append(text)
        if buffer and any(item.strip() for item in buffer):
            sections.append((current_title, "\n".join(buffer)))
        if not sections:
            sections = [("", "")]

        pages: List[ExtractedPage] = []
        for index, (title, body) in enumerate(sections, start=1):
            pages.append(
                ExtractedPage(
                    page_number=index,
                    text=clean_text(body),
                    section_title=title,
                )
            )

        result.pages = pages
        if not result.title:
            result.title = first_heading("\n".join(page.text for page in pages))
        result.metadata["section_count"] = len(pages)
        result.metadata["tables"] = self._table_count(document)
        result.metadata["note"] = (
            "DOCX files have no fixed pages; page numbers are heading sections."
        )
        if not result.has_content:
            result.warnings.append(
                "No readable text was found in this .docx file. It may contain only images; "
                "export it to PDF and upload that instead."
            )
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _iter_blocks(document) -> List[tuple]:
        """Yield ``(style_name, text)`` for paragraphs and tables in document order."""
        blocks: List[tuple] = []
        try:
            from docx.table import Table
            from docx.text.paragraph import Paragraph
            from docx.oxml.ns import qn
        except ImportError:  # pragma: no cover - python-docx always provides these
            return blocks

        body = document.element.body
        for child in body.iterchildren():
            if child.tag == qn("w:p"):
                paragraph = Paragraph(child, document)
                if paragraph.text and paragraph.text.strip():
                    style = paragraph.style.name if paragraph.style is not None else ""
                    blocks.append((style or "", paragraph.text.strip()))
            elif child.tag == qn("w:tbl"):
                table = Table(child, document)
                rows: List[str] = []
                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    if any(cells):
                        rows.append(" | ".join(cells))
                if rows:
                    blocks.append(("table", "\n".join(rows)))
        return blocks

    @staticmethod
    def _table_count(document) -> int:
        try:
            return len(document.tables)
        except Exception:  # pragma: no cover - defensive
            return 0