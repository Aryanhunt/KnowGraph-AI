"""
Document comparison service (brief §13).

Comparison is built the honest way: **the deterministic core computes the facts**
and the local model may only add *narrative*. Specifically:

* common topics  = intersection of the documents' extracted topics,
* unique topics  = topics present in one document only,
* sources        = the pages each document's topics came from,
* methodology / variations / narrative = produced by the local model when it is
  available, and each item keeps the document label(s) it refers to.

When the model is unavailable the caller still gets the deterministic comparison
plus an explicit note explaining that the narrative part is missing — no invented
methodology sections.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from config.settings import Settings, get_settings
from db.repositories import DocumentRepository, PageRepository
from services.llm import prompts
from services.llm.factory import get_llm_service
from utils.errors import ValidationError
from utils.logging_setup import get_logger
from utils.text import normalize_for_match

logger = get_logger(__name__)

NOT_FOUND = "Not found in document"


class CompareService:
    """Compare two or more of the user's documents."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        documents: Optional[DocumentRepository] = None,
        pages: Optional[PageRepository] = None,
        llm_service=None,
    ) -> None:
        self.settings = settings or get_settings()
        self.documents = documents or DocumentRepository()
        self.pages = pages or PageRepository()
        self._llm = llm_service

    @property
    def llm(self):
        if self._llm is None:
            self._llm = get_llm_service(self.settings)
        return self._llm

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def compare(self, user_id: Any, document_ids: Sequence[Any]) -> Dict[str, Any]:
        """Compare the selected documents (topic sets + optional LLM narrative)."""
        user_id = str(user_id)
        ids = [str(item) for item in document_ids or []]
        if len(ids) < 2:
            raise ValidationError(
                "Select at least two documents to compare.",
                code="not_enough_documents",
            )

        documents = self.documents.list_all_for_user(
            user_id, only_ready=True, document_ids=ids
        )
        if len(documents) < 2:
            raise ValidationError(
                "At least two *processed* documents are needed for a comparison.",
                hint="Wait for processing to finish, or choose different documents.",
                code="documents_not_ready",
            )

        labels = {}
        for index, document in enumerate(documents, start=1):
            labels[str(document["_id"])] = f"Doc {chr(64 + index)}"     # Doc A, Doc B, ...

        topic_sets = {
            str(document["_id"]): {
                normalize_for_match(str(topic)): str(topic)
                for topic in (document.get("topics") or [])
                if str(topic).strip()
            }
            for document in documents
        }

        common = self._common_topics(topic_sets)
        unique = self._unique_topics(topic_sets)
        sources = self._sources(documents, labels)

        result: Dict[str, Any] = {
            "documents": [
                {
                    "id": str(document["_id"]),
                    "label": labels[str(document["_id"])],
                    "title": document.get("title", ""),
                    "page_count": document.get("page_count", 0),
                    "subject": document.get("subject", ""),
                    "summary": document.get("summary", ""),
                    "summary_method": document.get("summary_method", ""),
                    "topics": document.get("topics", []),
                }
                for document in documents
            ],
            "common_topics": common,
            "unique_topics": unique,
            "methodology": [],
            "variations": [],
            "narrative": None,
            "sources": sources,
            "method": "deterministic topic comparison",
            "notes": [],
        }

        narrative = self._describe_with_llm(documents, labels, common, unique)
        if narrative:
            result.update(
                {
                    "methodology": narrative.get("methodology", []),
                    "variations": narrative.get("variations", []),
                    "narrative": narrative.get("summary"),
                    "method": "deterministic topic comparison + local model narrative",
                }
            )
        else:
            result["notes"].append(
                "The local model was unavailable, so methodology and variation analysis "
                "are omitted rather than guessed."
            )
        return result


# ------------------------------------------------------------------
    # Deterministic comparison
    # ------------------------------------------------------------------
    @staticmethod
    def _common_topics(topic_sets: Dict[str, Dict[str, str]]) -> List[Dict[str, Any]]:
        """Topics that appear in every selected document."""
        if not topic_sets:
            return []
        keys = [set(mapping) for mapping in topic_sets.values()]
        shared = set.intersection(*keys) if keys else set()
        result = []
        for key in sorted(shared):
            display = next(
                mapping[key] for mapping in topic_sets.values() if key in mapping
            )
            result.append({"topic": display, "documents": list(topic_sets.keys())})
        return result[:40]

    @staticmethod
    def _unique_topics(topic_sets: Dict[str, Dict[str, str]]) -> List[Dict[str, Any]]:
        """Topics that appear in exactly one document."""
        counts: Dict[str, int] = {}
        display: Dict[str, str] = {}
        owner: Dict[str, str] = {}
        for document_id, mapping in topic_sets.items():
            for key, label in mapping.items():
                counts[key] = counts.get(key, 0) + 1
                display.setdefault(key, label)
                owner.setdefault(key, document_id)
        unique: Dict[str, List[str]] = {}
        for key, count in counts.items():
            if count == 1:
                unique.setdefault(owner[key], []).append(display[key])
        return [
            {"document_id": document_id, "topics": sorted(items)[:25]}
            for document_id, items in unique.items()
        ]

    @staticmethod
    def _sources(documents: Sequence[Dict[str, Any]], labels: Dict[str, str]) -> List[Dict[str, Any]]:
        """Where each document's comparison facts came from."""
        sources = []
        for document in documents:
            document_id = str(document["_id"])
            sources.append(
                {
                    "document_id": document_id,
                    "label": labels.get(document_id, ""),
                    "title": document.get("title", ""),
                    "reference": f"{document.get('page_count', 0)} page(s) processed",
                    "topics": (document.get("topics") or [])[:10],
                    "summary_method": document.get("summary_method", ""),
                }
            )
        return sources

    def _describe_with_llm(
        self,
        documents: Sequence[Dict[str, Any]],
        labels: Dict[str, str],
        common: List[Dict[str, Any]],
        unique: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Optional narrative section (never used for the factual lists)."""
        try:
            if not self.llm.is_available():
                return None
            payload = self.llm.generate_json(
                prompts.build_compare_prompt(
                    [
                        {
                            "id": str(document["_id"]),
                            "label": labels.get(str(document["_id"]), ""),
                            "title": document.get("title", ""),
                            "page_count": document.get("page_count", 0),
                            "topics": document.get("topics", []),
                            "summary": document.get("summary", ""),
                        }
                        for document in documents
                    ]
                ),
                system=prompts.COMPARE_SYSTEM,
                max_tokens=900,
            )
            if not payload:
                return None
            return {
                "summary": str(payload.get("summary", "") or "")[:2000] or None,
                "methodology": _normalise_document_list(payload.get("methodology")),
                "variations": _normalise_variations(payload.get("variations")),
            }
        except Exception as exc:  # noqa: BLE001 - narrative is optional by design
            logger.warning("LLM comparison narrative skipped: %s", exc)
            return None


def _normalise_document_list(value: Any) -> List[Dict[str, Any]]:
    """Make the LLM's methodology list safe and explicit about missing fields."""
    if not isinstance(value, list):
        return []
    items: List[Dict[str, Any]] = []
    for entry in value:
        if isinstance(entry, dict):
            items.append(
                {
                    "document": str(entry.get("document", "")),
                    "methodology": str(entry.get("methodology", "") or NOT_FOUND),
                }
            )
    return items


def _normalise_variations(value: Any) -> List[Dict[str, Any]]:
    """Variations must always name the documents they refer to."""
    if not isinstance(value, list):
        return []
    items: List[Dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        documents = entry.get("documents")
        items.append(
            {
                "topic": str(entry.get("topic", "")),
                "note": str(entry.get("note", "")),
                "documents": [str(item) for item in documents] if isinstance(documents, list) else [],
            }
        )
    return items


def get_compare_service(settings: Optional[Settings] = None) -> CompareService:
    """Convenience factory used by the comparison route."""
    return CompareService(settings)
