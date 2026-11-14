"""
Relationship file parser — lets users supply their own edges (PDF, TXT, JSON, CSV).

The brief explicitly allows users to upload supplementary material; this is one such
feature: a "relationship file" that states which concepts relate to which other
concepts, in their own words. The parser normalizes each row and looks up the concept
labels in the user's existing graph so that aliases like "AI" and "Artificial
Intelligence" collapse to the same node.

Supported formats:
  * JSON  — [{"source": "...", "target": "...", "relation": "...", "why": "..."}]
  * JSONL — one JSON object per line (curated edge files): {"source": "...", "target": "...", "relation": "...", "page": 1}
  * CSV   — header row + columns: source, target, [relation], [why]
  * TXT   — one edge per line: "Source -> Target (relation) — why"
  * PDF   — text extracted first, then parsed as TXT (PyMuPDF/tesseract path)
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# A row as returned by the parser.
Row = Dict[str, Any]


# Patterns used across the text formats.
_ARROW = re.compile(r"\b->\b|\b→\b|\bto\b|\bdepends on\b|\brequires\b|\bbuilds on\b|\bbased on\b")
_RELATION_COLON = re.compile(r"\((?:relation(?:ship)?\s*)?[:=]\s*([^)]+?)\)", re.IGNORECASE)
_REASON_DASH = re.compile(r"\s*[-–—]\s*(?P<reason>.+)$")
_SPLIT = re.compile(r"\s*(?:-|–|→|to|depends on|requires|builds on|based on)\s*")


def _normalize_label(label: str) -> str:
    """Title-case-ish, strip punctuation, collapse internal whitespace."""
    label = label.strip().strip(".:;,-")
    if not label:
        return ""
    return re.sub(r"\s+", " ", label)


def _split_line(line: str) -> Tuple[str, str, str, str]:
    """Split a free-text line into (source, target, relation, reason).

    Heuristic-only — best-effort when the line does not match the structured
    "Source -> Target (relation) — why" shape.
    """
    line = line.split("#")[0].strip()
    if not line:
        return "", "", "", ""
    reason = ""
    m = _REASON_DASH.search(line)
    if m:
        reason = m.group("reason").strip()
        line = line[: m.start()].strip()

    relation = ""
    m = _RELATION_COLON.search(line)
    if m:
        relation = _normalize_label(m.group(1))
        line = _RELATION_COLON.sub("", line, count=1).strip()

    parts = _SPLIT.split(line, maxsplit=1)
    if len(parts) == 2:
        return _normalize_label(parts[0]), _normalize_label(parts[1]), relation, reason
    return _normalize_label(line), "", relation, reason


def _parse_txt(text: str) -> List[Row]:
    rows: List[Row] = []
    for line in text.splitlines():
        source, target, relation, reason = _split_line(line)
        if source and target:
            rows.append(
                {"source": source, "target": target, "relation": relation or "related_to", "why": reason}
            )
    return rows


def _row_from_data(item: Any, *, line_no: Optional[int] = None) -> Optional[Row]:
    """Normalize one JSON / JSONL object into a canonical edge row.

    ``source``/``target`` may also be written as ``from``/``to``; ``relation``
    accepts ``type`` as an alias. ``chapter`` and ``page`` are preserved so the
    route can record where the user noted the relationship (provenance).
    """
    if not isinstance(item, dict):
        return None
    source = _normalize_label(str(item.get("source") or item.get("from") or ""))
    target = _normalize_label(str(item.get("target") or item.get("to") or ""))
    if not source or not target:
        return None
    page = item.get("page")
    try:
        page = int(page) if page is not None and str(page).strip() != "" else None
    except (TypeError, ValueError):
        page = None
    return {
        "source": source,
        "target": target,
        "relation": str(item.get("relation") or item.get("type") or "related_to"),
        "why": str(item.get("why") or item.get("note") or item.get("description") or ""),
        "chapter": str(item.get("chapter") or "").strip(),
        "page": page,
    }


def _parse_json(text: str) -> List[Row]:
    payload = json.loads(text)
    if not isinstance(payload, list):
        payload = [payload]
    rows: List[Row] = []
    for item in payload:
        row = _row_from_data(item)
        if row is not None:
            rows.append(row)
    return rows


def _parse_jsonl(text: str) -> List[Row]:
    """Parse JSON Lines — one JSON object per line (e.g. a curated edge file).

    Each non-blank line is parsed independently, so a single malformed line is
    skipped instead of aborting the whole upload.
    """
    rows: List[Row] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        row = _row_from_data(item)
        if row is not None:
            rows.append(row)
    return rows


def _parse_csv(text: str) -> List[Row]:
    rows: List[Row] = []
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header:
        return rows
    # Map columns by name (case-insensitive) or by position.
    header_lower = [(h.strip().lower() if h else "") for h in header]
    src_idx = next((i for i, h in enumerate(header_lower) if h in ("source", "from", "src")), None)
    tgt_idx = next((i for i, h in enumerate(header_lower) if h in ("target", "to", "dst", "destination")), None)
    rel_idx = next((i for i, h in enumerate(header_lower) if h in ("relation", "type", "relation_type", "edge_type")), None)
    why_idx = next((i for i, h in enumerate(header_lower) if h in ("why", "note", "reason", "description", "evidence")), None)
    if src_idx is None or tgt_idx is None:
        # Fall back to position-based: source,target[,relation[,why]]
        src_idx, tgt_idx = 0, 1
        rel_idx = 2 if len(header) >= 3 else None
        why_idx = 3 if len(header) >= 4 else None
    for row in reader:
        if not row:
            continue
        source = _normalize_label(row[src_idx].strip()) if src_idx < len(row) else ""
        target = _normalize_label(row[tgt_idx].strip()) if tgt_idx < len(row) else ""
        if not source or not target:
            continue
        relation = _normalize_label(row[rel_idx].strip()) if rel_idx is not None and rel_idx < len(row) else "related_to"
        why = row[why_idx].strip() if why_idx is not None and why_idx < len(row) else ""
        rows.append({"source": source, "target": target, "relation": relation or "related_to", "why": why})
    return rows


class RelationshipParser:
    """Parse a relationship file (PDF/TXT/JSON/JSONL/CSV) into canonical edges."""

    # File types the parser accepts. PDF is accepted but must go through text
    # extraction first; the caller (route) does that extraction.
    ACCEPTED_EXTENSIONS: List[str] = ["pdf", "txt", "json", "jsonl", "csv"]
    ACCEPTED_MIME_PREFIXES: List[str] = [
        "application/pdf",
        "text/plain",
        "application/json",
        "application/x-jsonlines",
        "application/jsonlines",
        "text/x-jsonlines",
        "text/jsonlines",
        "text/csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ]

    def __init__(self, concept_repo: Any) -> None:
        """concept_repo must expose find_by_slug(user_id, slug) and list_for_user."""
        self._concept_repo = concept_repo

    def parse_file(self, file_path: Path, user_id: str, *, pdf_engine: Optional[str] = None) -> Dict[str, Any]:
        """Parse a file on disk and return matched/unmatched edge summaries."""
        ext = file_path.suffix.lstrip(".").lower()
        mime, _ = self._detect_mime(file_path)
        text = self._extract_text(file_path, ext, mime, pdf_engine)
        rows = self._parse(text)
        return self._resolve(user_id, rows)

    def parse_bytes(self, filename: str, data: bytes, user_id: str, *, pdf_engine: Optional[str] = None) -> Dict[str, Any]:
        """Parse raw bytes (for in-memory uploads)."""
        ext = Path(filename).suffix.lstrip(".").lower()
        text = self._extract_text_from_bytes(filename, data, ext)
        rows = self._parse(text)
        return self._resolve(user_id, rows)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _detect_mime(self, file_path: Path) -> Tuple[str, Optional[str]]:
        from utils.files import detect_mime_type
        return detect_mime_type(file_path, file_path.name)

    def _extract_text(self, file_path: Path, ext: str, mime: str, pdf_engine: Optional[str] = None) -> str:
        if ext == "pdf" or mime.startswith("application/pdf"):
            return self._extract_pdf_text(file_path, pdf_engine)
        if ext in ("txt", "md"):
            return file_path.read_text(encoding="utf-8", errors="replace")
        if ext in ("json", "jsonl"):
            return file_path.read_text(encoding="utf-8", errors="replace")
        if ext == "csv":
            return file_path.read_text(encoding="utf-8", errors="replace")
        # Fall back to treating as text.
        try:
            return file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""

    def _extract_text_from_bytes(self, filename: str, data: bytes, ext: str) -> str:
        if ext == "pdf":
            return self._extract_pdf_text_from_bytes(data)
        try:
            return data.decode("utf-8", errors="replace")
        except Exception:
            return data.decode("latin-1", errors="replace")

    def _extract_pdf_text(self, file_path: Path, pdf_engine: Optional[str] = None) -> str:
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(str(file_path))
            parts: List[str] = []
            for page in doc:
                parts.append(page.get_text("text") or "")
            doc.close()
            return "\n".join(parts)
        except Exception:
            pass

        try:
            from services.ocr import get_ocr_service
            ocr = get_ocr_service(self._resolve_settings())
            return ocr.extract_text(file_path)
        except Exception:
            pass

        return ""

    def _extract_pdf_text_from_bytes(self, data: bytes) -> str:
        try:
            import fitz
            import io
            doc = fitz.open(stream=io.BytesIO(data), filetype="pdf")
            parts: List[str] = []
            for page in doc:
                parts.append(page.get_text("text") or "")
            doc.close()
            return "\n".join(parts)
        except Exception:
            return ""

    def _resolve_settings(self):
        from config.settings import get_settings
        return get_settings()

    def _parse(self, text: str) -> List[Row]:
        text = text.strip()
        if not text:
            return []
        lower = text.lstrip().lower()
        if lower.startswith("["):
            # A JSON array of edges, e.g. [{"source": ...}, ...].
            return _parse_json(text)
        if lower.startswith("{"):
            # Either a single JSON object or a JSON Lines file (one object per
            # line). JSONL is not valid JSON as a whole, so try a full parse
            # first and gracefully fall back to line-by-line parsing.
            try:
                return _parse_json(text)
            except (json.JSONDecodeError, ValueError):
                return _parse_jsonl(text)
        if "," in text and "\n" in text:
            # Heuristic: CSV-like (header row + commas + newlines).
            return _parse_csv(text)
        # Default to free-text line parsing.
        return _parse_txt(text)

    def _resolve(self, user_id: str, rows: List[Row]) -> Dict[str, Any]:
        """Turn raw labels into slugs, tracking what matched."""
        matched: List[Dict[str, Any]] = []
        unmatched_sources: Dict[str, int] = {}
        unmatched_targets: Dict[str, int] = {}

        for row in rows:
            source_label = row.get("source") or ""
            target_label = row.get("target") or ""
            # User-curated relationships are the user's own statement, so store the
            # relation faithfully: canonical types are kept, obvious spelling variants
            # are normalised to canonical types, and any other type the user wrote is
            # kept verbatim instead of being silently dropped.
            relation = _normalize_relation(row.get("relation"))
            reason = str(row.get("why") or "").strip()

            source_slug = self._lookup_slug(user_id, source_label)
            target_slug = self._lookup_slug(user_id, target_label)

            if not source_slug:
                unmatched_sources[source_label] = unmatched_sources.get(source_label, 0) + 1
            if not target_slug:
                unmatched_targets[target_label] = unmatched_targets.get(target_label, 0) + 1

            if source_slug and target_slug:
                matched.append(
                    {
                        "source": source_label,
                        "target": target_label,
                        "source_slug": source_slug,
                        "target_slug": target_slug,
                        "relation": relation,
                        "why": reason,
                        "chapter": str(row.get("chapter") or "").strip(),
                        "page": row.get("page"),
                    }
                )

        return {
            "rows_total": len(rows),
            "edges_resolved": len(matched),
            "edges_unresolved": len(rows) - len(matched),
            "matched": matched,
            "unmatched_sources": dict(sorted(unmatched_sources.items(), key=lambda kv: -kv[1])[:20]),
            "unmatched_targets": dict(sorted(unmatched_targets.items(), key=lambda kv: -kv[1])[:20]),
        }

    def _lookup_slug(self, user_id: str, label: str) -> str:
        label = label.strip()
        if not label:
            return ""
        # Try an exact lookup first (fast path for known slugs).
        slug = slugify(label)
        if self._concept_repo.find_by_slug(user_id, slug):
            return slug
        # Try a normalized search across the user's concepts.
        candidates = self._concept_repo.list_for_user(user_id, search=label, limit=20)
        if not candidates:
            return ""
        # Pick the best match: exact normalized, or longest shared prefix.
        from utils.text import normalize_for_match
        norm = normalize_for_match(label)
        best = None
        best_score = -1
        for c in candidates:
            c_norm = c.get("normalized") or normalize_for_match(c.get("label", ""))
            score = 0
            if c_norm == norm:
                score = 1000
            elif c_norm.startswith(norm) or norm.startswith(c_norm):
                score = min(len(c_norm), len(norm))
            elif c.get("label", "").lower() == label.lower():
                score = 500
            if score > best_score:
                best_score = score
                best = c
        return (best or {}).get("slug", "")


def slugify(label: str) -> str:
    """Mirror the slugify used by concept_extractor so edge labels resolve consistently."""
    from utils.text import slugify as _slugify
    return _slugify(label)


# Canonical relation types the graph recognises (brief 9). Edges the extractor
# stores always use one of these; user-supplied relationships are normalised
# *into* this vocabulary where a clear variant exists, and any other type the
# user writes is still kept verbatim so nothing is silently lost.
_VALID_RELATIONS = frozenset(
    {
        "is_a", "is_a_type_of", "type_of", "part_of", "has_part", "component_of",
        "prerequisite_of", "requires", "depends_on", "used_for", "application_of",
        "example_of", "instance_of", "causes", "contrasts_with", "related_to",
        "builds_on", "extends", "defines", "subclass_of", "specializes",
        "implements", "contains", "includes", "precedes", "follows",
    }
)


# Variant labels that clearly mean the same canonical edge. Mapping these keeps
# the stored vocabulary tidy (no "is_an_example_of" next to "example_of") while
# still storing any relation the user genuinely coined.
_RELATION_ALIASES: Dict[str, str] = {
    "is_an_example_of": "example_of",
    "is_an_application_of": "application_of",
    "is_a_type_of": "is_a",
    "is_a_subfield_of": "part_of",
    "is_related_to": "related_to",
    "relates": "related_to",
    "relates_to": "related_to",
    "associated_with": "related_to",
    "based_on": "builds_on",
    "has_component": "contains",
    "contains_component": "contains",
}


def _normalize_relation(relation: Any) -> str:
    """Lowercase, map known variant labels to canonical types, and fall back to
    the user's own wording (never silently dropped)."""
    relation = str(relation or "related_to").strip().lower()
    if not relation:
        return "related_to"
    return _RELATION_ALIASES.get(relation, relation)
