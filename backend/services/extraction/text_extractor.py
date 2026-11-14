"""
Plain-text and Markdown extractor.

Neither format has fixed pages, so sections are derived from structure and the
resulting "page numbers" are section numbers. The section title is stored on the
page so a citation can read "Notes.md — Section 3: Normalization" instead of
pretending to know a page that does not exist.

Form-feed characters (``\\f``), which many text exports use as a page break, are
honoured when present.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from services.extraction.base import DocumentExtractor, ExtractedPage, ExtractionResult
from utils.text import clean_text, first_heading

# Markdown headings (#, ##, ...) and numbered/lettered headings common in notes.
_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_NUMBERED_HEADING = re.compile(r"^(?:unit|chapter|module|topic|section)\s+\d+[.:)]?\s+(.*\S)$", re.IGNORECASE)
_NUMBERED_HEADING_SHORT = re.compile(r"^\d+(?:\.\d+){0,3}[.:)]?\s+([A-Z][^.!?]{2,70})$")
_ALLCAPS_HEADING = re.compile(r"^[A-Z][A-Z0-9 \-&/()]{3,60}$")


class TextExtractor(DocumentExtractor):
    """Extractor for ``.txt`` and ``.md`` files."""

    source_type = "text"
    extensions = ("txt", "md", "markdown")

    def extract(
        self,
        path: Path,
        *,
        document_id: str,
        document_title: str = "",
        page_image_dir: Optional[Path] = None,
    ) -> ExtractionResult:
        result = ExtractionResult(source_type=self.source_type, method="plain_text", title=document_title)

        # Try UTF-8 first; latin-1 never fails and keeps old notes readable.
        text = ""
        for encoding in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                text = path.read_text(encoding=encoding)
                result.metadata["encoding"] = encoding
                break
            except UnicodeDecodeError:
                continue
            except OSError as exc:
                result.warnings.append(f"The file could not be read: {exc}")
                return result
        if not text:
            result.warnings.append("The file appears to be empty.")
            result.pages = [ExtractedPage(page_number=1, text="")]
            return result

        if not result.title:
            result.title = first_heading(text)

        raw_sections = self._split_sections(text)
        pages: List[ExtractedPage] = []
        for index, (title, body) in enumerate(raw_sections, start=1):
            pages.append(
                ExtractedPage(
                    page_number=index,
                    text=clean_text(body),
                    section_title=clean_text(title) if title else "",
                )
            )
        result.pages = pages
        result.metadata["section_count"] = len(pages)
        result.metadata["note"] = "Text files have no fixed pages; page numbers are section numbers."
        return result

    # ------------------------------------------------------------------
    # Section splitting
    # ------------------------------------------------------------------
    @staticmethod
    def _is_heading(line: str) -> bool:
        stripped = line.strip()
        if not stripped or len(stripped) > 90:
            return False
        if _MARKDOWN_HEADING.match(stripped):
            return True
        if _NUMBERED_HEADING.match(stripped):
            return True
        if _ALLCAPS_HEADING.match(stripped) and len(stripped.split()) <= 8:
            return True
        return bool(_NUMBERED_HEADING_SHORT.match(stripped))

    def _split_sections(self, text: str) -> List[tuple]:
        """Return ``[(section_title, section_body), ...]``."""
        # Honour explicit page breaks first: they are the most reliable signal.
        if "\f" in text:
            return [("", page) for page in text.split("\f") if page.strip()]

        sections: List[tuple] = []
        current_title = ""
        buffer: List[str] = []
        for line in text.replace("\r\n", "\n").split("\n"):
            if self._is_heading(line):
                if buffer and any(item.strip() for item in buffer):
                    sections.append((current_title, "\n".join(buffer)))
                current_title = _MARKDOWN_HEADING.sub(r"\2", line.strip()).strip()
                buffer = [line]
            else:
                buffer.append(line)
        if buffer and any(item.strip() for item in buffer):
            sections.append((current_title, "\n".join(buffer)))

        # A file without any headings is a single section.
        if not sections:
            return [("", text)]
        return sections