"""
Chunking (brief §4, pipeline stage "Chunking").

Design goals, in order of importance:

1. never break a page boundary silently — a chunk always knows its page number,
2. respect prose structure — split on paragraph/sentence boundaries first and only
   fall back to hard cuts for pathological input (OCR blocks, giant tables),
3. keep a configurable overlap so a definition split across two chunks is still
   retrievable.

Chunks are produced per page, so the retrieved chunk → page → document citation
chain stays exact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence

from utils.text import split_sentences

#: Guard against a single "word" (e.g. a base64 blob) being unbounded.
MAX_TOKEN_CHARS = 400


@dataclass
class TextChunk:
    """One embeddable passage."""

    text: str
    page_number: int
    chunk_index: int
    section_title: str = ""

    @property
    def char_count(self) -> int:
        return len(self.text)


def split_paragraphs(text: str) -> List[str]:
    """Split on blank lines; single newlines are kept inside a paragraph."""
    paragraphs = [block.strip() for block in (text or "").split("\n\n")]
    return [paragraph for paragraph in paragraphs if paragraph]


def _split_long_paragraph(paragraph: str, chunk_size: int) -> List[str]:
    """Break an oversized paragraph on sentence boundaries, then hard-cut."""
    pieces: List[str] = []
    buffer = ""
    for sentence in split_sentences(paragraph):
        if len(sentence) > chunk_size:
            # A single enormous sentence: cut it into fixed windows.
            if buffer.strip():
                pieces.append(buffer.strip())
                buffer = ""
            for start in range(0, len(sentence), chunk_size):
                pieces.append(sentence[start : start + chunk_size].strip())
            continue
        if len(buffer) + len(sentence) + 1 <= chunk_size:
            buffer = f"{buffer} {sentence}".strip()
        else:
            if buffer.strip():
                pieces.append(buffer.strip())
            buffer = sentence
    if buffer.strip():
        pieces.append(buffer.strip())
    return [piece for piece in pieces if piece]


def _overlap_tail(text: str, overlap: int) -> str:
    """
    Return the tail of ``text`` used as context for the next chunk.

    The cut is moved to the nearest sentence boundary so the overlap does not
    start mid-word.
    """
    if overlap <= 0 or not text:
        return ""
    tail = text[-overlap:]
    boundary = tail.find(". ")
    if 0 <= boundary < len(tail) - 20:
        return tail[boundary + 2 :].strip()
    return tail.strip()


def chunk_text(
    text: str,
    *,
    page_number: int,
    chunk_size: int,
    overlap: int,
    start_index: int = 0,
    section_title: str = "",
) -> List[TextChunk]:
    """Chunk one page's text into overlapping, page-aware passages."""
    if not (text or "").strip():
        return []

    chunk_size = max(200, chunk_size)
    overlap = max(0, min(overlap, chunk_size // 2))

    # Build a linear list of units that each fit in a chunk.
    units: List[str] = []
    for paragraph in split_paragraphs(text):
        if len(paragraph) <= chunk_size:
            units.append(paragraph)
        else:
            units.extend(_split_long_paragraph(paragraph, chunk_size))

    chunks: List[TextChunk] = []
    buffer = ""
    index = start_index

    for unit in units:
        candidate = f"{buffer}\n\n{unit}".strip() if buffer else unit
        if len(candidate) <= chunk_size:
            buffer = candidate
            continue

        # Flush the current buffer, then carry overlap into the next chunk.
        if buffer.strip():
            chunks.append(
                TextChunk(text=buffer.strip(), page_number=page_number, chunk_index=index,
                          section_title=section_title)
            )
            index += 1
            tail = _overlap_tail(buffer, overlap)
            buffer = f"{tail}\n\n{unit}".strip() if tail else unit
            if len(buffer) > chunk_size:
                # The overlap itself pushed us over the limit; drop it.
                buffer = unit
        else:
            buffer = unit

    if buffer.strip():
        chunks.append(
            TextChunk(text=buffer.strip(), page_number=page_number, chunk_index=index,
                      section_title=section_title)
        )
    return chunks


def chunk_pages(
    pages: Sequence,
    *,
    chunk_size: int,
    overlap: int,
) -> List[TextChunk]:
    """
    Chunk a list of extracted pages.

    Accepts any objects exposing ``page_number``, ``text`` and (optionally)
    ``section_title`` — i.e. :class:`~services.extraction.base.ExtractedPage`.
    ``chunk_index`` is global across the document so chunk ids stay unique.
    """
    chunks: List[TextChunk] = []
    index = 0
    for page in pages:
        produced = chunk_text(
            getattr(page, "text", "") or "",
            page_number=int(getattr(page, "page_number", 1)),
            chunk_size=chunk_size,
            overlap=overlap,
            start_index=index,
            section_title=getattr(page, "section_title", "") or "",
        )
        chunks.extend(produced)
        index += len(produced)
    return chunks


def chunk_plain_text(
    text: str,
    *,
    chunk_size: int,
    overlap: int,
    page_number: int = 1,
) -> List[TextChunk]:
    """Convenience wrapper used by search snippets and tests."""
    return chunk_text(
        text, page_number=page_number, chunk_size=chunk_size, overlap=overlap
    )


def iter_chunk_windows(text: str, window: int = 200, step: int = 100) -> Iterable[str]:
    """Sliding char windows — used by keyword highlighting in search results."""
    if not text:
        return []
    windows: List[str] = []
    for start in range(0, max(1, len(text) - window + 1), step):
        windows.append(text[start : start + window])
    return windows