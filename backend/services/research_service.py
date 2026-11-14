"""
Research paper mode (brief §14).

Extracts the standard research-paper structure and — this is the important part —
**never invents a field**: anything not present in the paper is reported as
``"Not found in document"`` with ``found: false``, exactly as the brief requires.

Two layers:

1. **Heuristic pre-extraction** (no model): title from the first page, author-like
   lines, abstract block, keyword list, DOI/venue lines, and the page where each
   field was seen. This always works.
2. **LLM structure pass** (optional): the local model fills objective, methodology,
   dataset, results, limitations and conclusion from the paper text. Every returned
   field is checked against ``NOT_FOUND``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from config.settings import Settings, get_settings
from db.repositories import DocumentRepository, PageRepository
from services.compare_service import NOT_FOUND, CompareService
from services.llm import prompts
from services.llm.factory import get_llm_service
from utils.errors import NotFoundError
from utils.logging_setup import get_logger
from utils.text import is_meaningful_text, truncate

logger = get_logger(__name__)

#: Field list shown in the UI (brief §14).
FIELDS = (
    "title",
    "authors",
    "abstract",
    "keywords",
    "objective",
    "methodology",
    "dataset",
    "results",
    "limitations",
    "conclusion",
)

_AUTHOR_LINE = re.compile(
    r"^(?:[A-Z][a-zA-Z.'\-]+(?:\s+[A-Z][a-zA-Z.'\-]+){0,3})(?:\s*,\s*[A-Z][a-zA-Z.'\-]+(?:\s+[A-Z][a-zA-Z.'\-]+){0,3})*"
    r"(?:\s*[\u2020\u2021*0-9]|$)"
)
_KEYWORDS_LINE = re.compile(r"^\s*(?:keywords?|key\s*words?)\s*[:\-]\s*(?P<body>.+)$", re.IGNORECASE)
_ABSTRACT_LINE = re.compile(r"^\s*abstract\s*[:\-]?\s*(?P<body>.*)$", re.IGNORECASE)
_DOI_LINE = re.compile(r"(doi|https?://doi\.org|arxiv|ieee|springer|elsevier)", re.IGNORECASE)
_SECTION_HEADS = {
    "methodology": ("methodology", "methods", "proposed method", "approach", "system design"),
    "dataset": ("dataset", "data set", "data collection", "corpus", "benchmark"),
    "results": ("results", "evaluation", "experiments", "findings"),
    "limitations": ("limitations", "threats to validity", "future work"),
    "conclusion": ("conclusion", "conclusions", "concluding remarks"),
    "objective": ("objective", "aim", "motivation", "problem statement", "introduction"),
}


class ResearchService:
    """Structured reading of research papers."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        documents: Optional[DocumentRepository] = None,
        pages: Optional[PageRepository] = None,
        compare_service: Optional[CompareService] = None,
        llm_service=None,
    ) -> None:
        self.settings = settings or get_settings()
        self.documents = documents or DocumentRepository()
        self.pages = pages or PageRepository()
        self.compare = compare_service or CompareService(self.settings)
        self._llm = llm_service

    @property
    def llm(self):
        if self._llm is None:
            self._llm = get_llm_service(self.settings)
        return self._llm

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------
    def extract(self, user_id: Any, document_id: Any, *, use_llm: bool = True) -> Dict[str, Any]:
        """Return the paper structure with per-field provenance."""
        document = self.documents.find_for_user(document_id, user_id)
        if not document:
            raise NotFoundError("Document not found.", code="document_not_found")

        pages = self.pages.list_for_document(str(document["_id"]))
        if not pages:
            raise NotFoundError(
                "This document has no extracted pages yet.",
                code="document_not_processed",
                hint="Wait for processing to finish, then open Research mode again.",
            )

        fields = self._heuristic_fields(document, pages)
        method = "heuristic extraction"

        if use_llm:
            llm_fields = self._llm_fields(pages)
            if llm_fields:
                method = "heuristic extraction + local model structure pass"
                for key, value in llm_fields.items():
                    current = fields.get(key, {})
                    if not current.get("found") and value not in ("", NOT_FOUND):
                        fields[key] = {"value": value, "found": True, "source": current.get("source")}

        return {
            "document": {
                "id": str(document["_id"]),
                "title": document.get("title", ""),
                "page_count": document.get("page_count", 0),
                "subject": document.get("subject", ""),
                "is_research_paper": document.get("is_research_paper", False),
                "summary": document.get("summary", ""),
            },
            "fields": fields,
            "found_count": sum(1 for field in fields.values() if field.get("found")),
            "total_fields": len(FIELDS),
            "method": method,
            "not_found_label": NOT_FOUND,
        }


# ------------------------------------------------------------------
    # Heuristic extraction (no model required)
    # ------------------------------------------------------------------
    def _heuristic_fields(
        self, document: Dict[str, Any], pages: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """Find title, authors, abstract, keywords and sections from page text."""
        first_page = pages[0].get("text", "") or ""
        lines = [line.strip() for line in first_page.split("\n") if line.strip()]

        fields: Dict[str, Dict[str, Any]] = {name: _missing() for name in FIELDS}

        # Title: the stored document title, or the longest early line.
        title = (document.get("title") or "").strip()
        if not title and lines:
            title = max(lines[:6], key=len)
        fields["title"] = {"value": title, "found": bool(title), "source": _page_ref(pages, 0)}

        # Authors: author-like lines on the first page.
        authors = [
            line
            for line in lines[1:12]
            if _AUTHOR_LINE.match(line) and len(line.split()) <= 12 and not _DOI_LINE.search(line)
        ]
        if authors:
            fields["authors"] = {
                "value": ", ".join(authors[:6]),
                "found": True,
                "source": _page_ref(pages, 0),
            }

        # Abstract and keywords (usually on page 1).
        for page_index, page in enumerate(pages[:3]):
            text = page.get("text", "") or ""
            if not fields["abstract"]["found"]:
                abstract = _extract_abstract(text)
                if abstract:
                    fields["abstract"] = {
                        "value": truncate(abstract, 1500),
                        "found": True,
                        "source": _page_ref(pages, page_index),
                    }
            if not fields["keywords"]["found"]:
                keywords = _extract_keywords(text)
                if keywords:
                    fields["keywords"] = {
                        "value": keywords,
                        "found": True,
                        "source": _page_ref(pages, page_index),
                    }

        # Section-based fields (methodology, dataset, results, ...).
        for page_index, page in enumerate(pages):
            section = _find_section(page.get("text", "") or "")
            if not section:
                continue
            for field_name, heads in _SECTION_HEADS.items():
                if fields[field_name]["found"]:
                    continue
                if any(head in section["heading"] for head in heads):
                    body = truncate(section["body"], 900)
                    if is_meaningful_text(body, 60):
                        fields[field_name] = {
                            "value": body,
                            "found": True,
                            "source": _page_ref(pages, page_index),
                        }
        return fields

    def _llm_fields(self, pages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Optional structure pass with the local model."""
        try:
            if not self.llm.is_available():
                return {}
            sample = "\n\n".join(
                f"[page {page.get('page_number')}]\n{(page.get('text') or '')[:2500]}"
                for page in pages[:4]
            )
            payload = self.llm.generate_json(
                prompts.build_research_prompt(sample),
                system=prompts.RESEARCH_SYSTEM,
                max_tokens=1200,
            )
        except Exception as exc:  # noqa: BLE001 - heuristics already produced a result
            logger.warning("LLM research extraction skipped: %s", exc)
            return {}
        if not payload:
            return {}

        cleaned: Dict[str, Any] = {}
        for field in FIELDS:
            value = payload.get(field)
            if isinstance(value, list):
                value = ", ".join(str(item) for item in value if str(item).strip())
            text = str(value if value is not None else "").strip()
            # Anything the model reports as missing stays missing — never guessed.
            if text and NOT_FOUND.lower() not in text.lower():
                cleaned[field] = truncate(text, 1500)
        return cleaned


# ------------------------------------------------------------------
    # Actions (the buttons from brief §14)
    # ------------------------------------------------------------------
    def action(self, user_id: Any, document_id: Any, action: str) -> Dict[str, Any]:
        """
        Run one research-paper action:
        ``summarize``, ``methodology``, ``limitations``, ``study_notes``.
        """
        document = self.documents.find_for_user(document_id, user_id)
        if not document:
            raise NotFoundError("Document not found.", code="document_not_found")

        pages = self.pages.list_for_document(str(document["_id"]))
        sample = "\n\n".join((page.get("text") or "")[:2500] for page in pages[:4])
        if not is_meaningful_text(sample, 200):
            raise NotFoundError(
                "There is not enough extracted text to analyse.",
                code="document_not_processed",
            )

        instructions = {
            "summarize": "Write a structured summary: objective, method, findings, limitations.",
            "methodology": "Explain the methodology in plain language, step by step.",
            "limitations": "List the limitations explicitly stated in the paper. "
                           "If none are stated, say so.",
            "study_notes": "Write revision notes in short bullet points for an exam.",
        }
        if action not in instructions:
            raise NotFoundError(
                f"Unknown research action '{action}'.",
                code="unknown_action",
                hint=f"Supported actions: {', '.join(instructions)}.",
            )

        prompt = (
            f"{instructions[action]}\n"
            "Use only the paper text below. If something is not stated, write "
            f"'{NOT_FOUND}' instead of guessing.\n\n--- BEGIN PAPER ---\n{sample}\n--- END PAPER ---"
        )
        response = self.llm.generate(prompt, system=prompts.RESEARCH_SYSTEM, max_tokens=900)
        return {
            "action": action,
            "document_id": str(document["_id"]),
            "title": document.get("title", ""),
            "answer": response.text or "The local model returned an empty answer.",
            "model": response.model or self.settings.llm_model,
            "based_on_documents": True,
        }

    def compare_papers(self, user_id: Any, document_ids: List[Any]) -> Dict[str, Any]:
        """Delegate to the comparison service (brief §13/§14)."""
        return self.compare.compare(user_id, document_ids)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------
def _missing() -> Dict[str, Any]:
    return {"value": NOT_FOUND, "found": False, "source": None}


def _page_ref(pages: List[Dict[str, Any]], index: int) -> Optional[Dict[str, Any]]:
    if index < 0 or index >= len(pages):
        return None
    page = pages[index]
    return {"page_number": page.get("page_number"), "ocr_used": page.get("ocr_used", False)}


def _extract_abstract(text: str) -> str:
    """Pull the abstract block out of a page when it is present."""
    lines = [line.strip() for line in (text or "").split("\n")]
    for index, line in enumerate(lines):
        match = _ABSTRACT_LINE.match(line)
        if not match:
            continue
        collected = [match.group("body").strip()] if match.group("body") else []
        for following in lines[index + 1 : index + 14]:
            if not following or _KEYWORDS_LINE.match(following) or len(following) < 3:
                break
            collected.append(following)
        body = " ".join(collected).strip()
        if is_meaningful_text(body, 80):
            return body
    return ""


def _extract_keywords(text: str) -> str:
    for line in (text or "").split("\n"):
        match = _KEYWORDS_LINE.match(line)
        if match:
            body = match.group("body").strip()
            if is_meaningful_text(body, 3):
                return body[:300]
    return ""


def _find_section(text: str) -> Optional[Dict[str, str]]:
    """
    Return ``{"heading": ..., "body": ...}`` for the first recognised section.

    Only the heading plus the following lines are returned — enough to decide
    whether a field exists without dumping the whole paper into the UI.
    """
    lines = (text or "").split("\n")
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or len(stripped) > 70:
            continue
        lowered = stripped.lower().rstrip(":.")
        if any(
            lowered == head or lowered.startswith(head + " ") for head in SECTION_HEADINGS
        ):
            body = "\n".join(lines[index + 1 : index + 12]).strip()
            if body:
                return {"heading": lowered, "body": body}
    return None


#: Flat list of every recognised section heading.
SECTION_HEADINGS = [head for heads in _SECTION_HEADS.values() for head in heads]


def get_research_service(settings: Optional[Settings] = None) -> ResearchService:
    """Convenience factory used by the research routes."""
    return ResearchService(settings)
