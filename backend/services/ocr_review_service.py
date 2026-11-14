"""
OCR review service — correction workflow and correction-aware reindexing.

Responsibilities:

* validate a page/document pair belongs to the requesting user,
* store user corrections separately from the original OCR output (audit trail),
* mark pages as reviewed,
* re-run OCR for a single page,
* trigger reindexing so search/RAG prefer corrected text.

Text selection rule (single source of truth)::

    effective_text = corrected_text if a valid correction exists else original_text
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from config.settings import Settings, get_settings
from db.repositories import ChunkRepository, DocumentRepository, PageRepository
from models.domain import utcnow
from utils.errors import NotFoundError, ValidationError
from utils.logging_setup import get_logger
from utils.text import clean_text

logger = get_logger(__name__)


class OcrReviewService:
    """User-facing OCR review and correction operations."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        documents: Optional[DocumentRepository] = None,
        pages: Optional[PageRepository] = None,
        chunks: Optional[ChunkRepository] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.documents = documents or DocumentRepository()
        self.pages = pages or PageRepository()
        self.chunks = chunks or ChunkRepository()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _document(self, document_id: Any, user_id: Any) -> Dict[str, Any]:
        document = self.documents.find_for_user(document_id, user_id)
        if not document:
            raise NotFoundError("Document not found.", code="document_not_found")
        return document

    def _page(self, document_id: Any, page_number: int, user_id: Any) -> Dict[str, Any]:
        self._document(document_id, user_id)
        page = self.pages.get_page(document_id, int(page_number))
        if not page:
            raise NotFoundError(
                f"Page {page_number} was not found in this document.",
                code="page_not_found",
            )
        return page

    @staticmethod
    def effective_text(page: Dict[str, Any]) -> str:
        """corrected_text if a valid correction exists, else original text."""
        corrected = (page.get("corrected_text") or "").strip()
        return corrected if corrected else (page.get("text") or "")

    @staticmethod
    def serialize_page(page: Dict[str, Any]) -> Dict[str, Any]:
        """Shape a page for the OCR review UI."""
        return {
            "document_id": str(page.get("document_id", "")),
            "page_number": page.get("page_number"),
            "text": page.get("text", ""),
            "original_text": page.get("original_text", "") or page.get("text", ""),
            "corrected_text": page.get("corrected_text", ""),
            "effective_text": OcrReviewService.effective_text(page),
            "correction_status": page.get("correction_status", ""),
            "correction_version": page.get("correction_version", 0),
            "reviewed_by": page.get("reviewed_by"),
            "reviewed_at": page.get("reviewed_at"),
            "ocr_used": page.get("ocr_used", False),
            "ocr_confidence": page.get("ocr_confidence"),
            "ocr_engine": page.get("ocr_engine", ""),
            "ocr_preprocessing": page.get("ocr_preprocessing") or {},
            "image_path": page.get("image_path"),
            "char_count": page.get("char_count", 0),
            "section_title": page.get("section_title", ""),
            "quality_label": page.get("quality_label", ""),
            "quality_metrics": page.get("quality_metrics") or {},
            "quality_warnings": page.get("quality_warnings") or [],
            "needs_reindex": page.get("needs_reindex", False),
            "has_image": bool(page.get("image_path")),
        }

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def list_pages(self, document_id: Any, user_id: Any) -> Dict[str, Any]:
        """All pages of a document with review metadata, plus a review summary."""
        document = self._document(document_id, user_id)
        rows = self.pages.list_for_document(document_id)
        pages = [self.serialize_page(row) for row in rows]
        summary = {
            "total": len(pages),
            "ocr_pages": sum(1 for p in pages if p["ocr_used"]),
            "corrected": sum(1 for p in pages if p["correction_status"] == "corrected"),
            "reviewed": sum(1 for p in pages if p["correction_status"] == "reviewed"),
            "flagged": sum(
                1
                for p in pages
                if p["quality_label"] in {"poor", "needs_review", "unreadable"}
            ),
            "needs_reindex": sum(1 for p in pages if p["needs_reindex"]),
        }
        return {
            "document": {
                "id": str(document["_id"]),
                "title": document.get("title", ""),
                "processing_status": document.get("processing_status", ""),
            },
            "pages": pages,
            "summary": summary,
        }

    def get_page_report(self, document_id: Any, page_number: int, user_id: Any) -> Dict[str, Any]:
        """Quality report for one page."""
        page = self._page(document_id, page_number, user_id)
        return self.serialize_page(page)

    # ------------------------------------------------------------------
    # Corrections
    # ------------------------------------------------------------------
    def save_correction(
        self,
        document_id: Any,
        page_number: int,
        user_id: Any,
        corrected_text: str,
        *,
        mark_reviewed: bool = False,
    ) -> Dict[str, Any]:
        """
        Save a user correction for one page.

        The original OCR text is never modified. ``text`` keeps serving the UI
        until reindexing runs, after which it equals the corrected text.
        """
        page = self._page(document_id, page_number, user_id)
        text = str(corrected_text or "")
        if not text.strip():
            raise ValidationError(
                "The corrected text cannot be empty.",
                hint="Clear the correction with the reset endpoint instead.",
            )
        if len(text) > 200_000:
            raise ValidationError(
                "The corrected text is too long (max 200,000 characters)."
            )

        cleaned = clean_text(text)
        fields = {
            "corrected_text": cleaned,
            "correction_status": "corrected",
            "correction_version": int(page.get("correction_version", 0) or 0) + 1,
            "needs_reindex": True,
            "updated_at": utcnow(),
        }
        if mark_reviewed:
            fields["correction_status"] = "reviewed"
            fields["reviewed_by"] = str(user_id)
            fields["reviewed_at"] = utcnow()

        updated = self.pages.update_page_fields(document_id, int(page_number), fields)
        logger.info(
            "Correction saved for document %s page %s (v%s)",
            document_id,
            page_number,
            fields["correction_version"],
        )
        merged = {**page, **fields}
        return self.serialize_page(updated or merged)

    def reset_correction(self, document_id: Any, page_number: int, user_id: Any) -> Dict[str, Any]:
        """Drop the correction and return the page to its original OCR text."""
        self._page(document_id, page_number, user_id)
        fields = {
            "corrected_text": "",
            "correction_status": "",
            "reviewed_by": None,
            "reviewed_at": None,
            "needs_reindex": True,   # re-index back to the original text
            "updated_at": utcnow(),
        }
        updated = self.pages.update_page_fields(document_id, int(page_number), fields)
        logger.info("Correction reset for document %s page %s", document_id, page_number)
        return self.serialize_page(updated or {})

    def mark_reviewed(self, document_id: Any, page_number: int, user_id: Any) -> Dict[str, Any]:
        """Mark a page as reviewed without necessarily correcting it."""
        page = self._page(document_id, page_number, user_id)
        fields = {
            "reviewed_by": str(user_id),
            "reviewed_at": utcnow(),
            "updated_at": utcnow(),
        }
        if not page.get("correction_status"):
            fields["correction_status"] = "reviewed"
        updated = self.pages.update_page_fields(document_id, int(page_number), fields)
        merged = {**page, **fields}
        return self.serialize_page(updated or merged)

    def rerun_page_ocr(self, document_id: Any, page_number: int, user_id: Any) -> Dict[str, Any]:
        """
        Re-run OCR for one page using the preserved page image.

        Replaces the page's OCR-derived fields. A fresh OCR pass supersedes any
        previous correction (the image is the ground truth the user asked for).
        """
        self._document(document_id, user_id)
        page = self._page(document_id, page_number, user_id)

        image_path = page.get("image_path")
        if not image_path or not Path(image_path).exists():
            raise ValidationError(
                f"No stored page image exists for page {page_number}.",
                hint="Reprocess the document, or re-upload the original file.",
                code="page_image_missing",
            )

        from services.ocr.factory import get_ocr_service
        from services.ocr.quality import assess_quality

        ocr = get_ocr_service(self.settings)
        if not ocr.is_available():
            from utils.errors import ocr_unavailable

            raise ocr_unavailable(ocr.unavailable_reason())

        result = ocr.recognize_image(Path(image_path), page_number=int(page_number))
        cleaned = clean_text(result.text)
        report = assess_quality(
            cleaned,
            result.confidence,
            ocr_used=True,
            ocr_ok=result.ok,
            engine=result.engine,
        )

        fields = {
            "text": cleaned,
            "original_text": cleaned,
            "ocr_used": True,
            "ocr_confidence": result.confidence,
            "ocr_engine": result.engine,
            "ocr_run_at": utcnow(),
            "quality_label": report.label,
            "quality_metrics": report.to_dict()["metrics"],
            "quality_warnings": report.warnings,
            "char_count": len(cleaned),
            "updated_at": utcnow(),
            # A fresh OCR pass supersedes any previous correction.
            "corrected_text": "",
            "correction_status": "",
            "correction_version": 0,
            "needs_reindex": True,
        }
        updated = self.pages.update_page_fields(document_id, int(page_number), fields)
        logger.info("Re-ran OCR for document %s page %s", document_id, page_number)
        merged = {**page, **fields}
        return self.serialize_page(updated or merged)

    # ------------------------------------------------------------------
    # Correction-aware reindexing
    # ------------------------------------------------------------------
    def _pages_for_chunking(self, document_id: str) -> list:
        """Pages shaped for the chunker, with effective_text applied.

        The chunker reads attributes (getattr), so we wrap the stored page dicts
        in a tiny view object — the same pattern the pipeline uses.
        """

        class _PageView:
            def __init__(self, payload: Dict[str, Any], text: str) -> None:
                self.page_number = payload.get("page_number", 1)
                self.text = text
                self.section_title = payload.get("section_title", "")

        rows = self.pages.list_for_document(document_id)
        return [
            _PageView(row, self.effective_text(row))
            for row in rows
        ]

    def reindex_document(
        self,
        document_id: Any,
        user_id: Any,
        *,
        rebuild_graph: bool = True,
        settings: Optional[Settings] = None,
    ) -> Dict[str, Any]:
        """
        Rebuild chunks + embeddings (+ optionally the graph) from the pages'
        *effective* text, honouring corrections.

        Idempotent: chunk/vector ids are deterministic
        (``{document_id}:{chunk_index}``), so re-running replaces instead of
        duplicating. On failure the corrected text is preserved and
        ``needs_reindex`` stays set so a later retry can complete the job.
        """
        settings = settings or self.settings
        document = self._document(document_id, user_id)
        doc_id = str(document["_id"])

        pages_payload = self._pages_for_chunking(doc_id)
        if not pages_payload:
            raise ValidationError(
                "This document has no pages to index.", code="no_pages"
            )

        from services.chunking import chunk_pages

        chunks = [
            chunk
            for chunk in chunk_pages(
                pages_payload,
                chunk_size=settings.chunk_size,
                overlap=settings.chunk_overlap,
            )
            if chunk.text.strip()
        ]
        if not chunks:
            raise ValidationError(
                "No text chunks could be created from this document.",
                code="no_chunks",
            )

        return self._index_chunks(document, chunks, settings)

    def _index_chunks(self, document: Dict[str, Any], chunks: list, settings: Settings) -> Dict[str, Any]:
        """Embed + store chunks + upsert vectors, idempotently."""
        from services.embeddings.factory import get_embedding_service
        from services.vector.base import VectorRecord
        from services.vector.factory import get_vector_store
        from utils.errors import AppError

        doc_id = str(document["_id"])
        user_id = str(document["user_id"])
        source_type = document.get("file_type", "pdf")
        title = document.get("title", "")

        embedding_service = get_embedding_service(settings)
        embedding_result = embedding_service.embed_texts([c.text for c in chunks])
        if not embedding_result.ok or len(embedding_result.vectors) != len(chunks):
            # Do NOT clear needs_reindex — the correction stays pending.
            reason = embedding_result.error or "The embedding model did not return vectors."
            logger.error("Reindex failed for %s: %s", doc_id, reason)
            raise AppError(
                f"Re-indexing failed: {reason}",
                code="reindex_embedding_failed",
                status_code=503,
                hint=(
                    "Your correction is saved. Check that Ollama is running and "
                    "the embedding model is installed, then retry reindexing."
                ),
            )

        vector_store = get_vector_store(settings)
        chunk_documents = []
        vector_records = []
        for chunk, vector in zip(chunks, embedding_result.vectors):
            vector_id = f"{doc_id}:{chunk.chunk_index}"
            chunk_documents.append(
                {
                    "document_id": doc_id,
                    "user_id": user_id,
                    "page_number": chunk.page_number,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "source_type": source_type,
                    "embedding_id": vector_id,
                    "char_count": chunk.char_count,
                    "metadata": {
                        "section_title": chunk.section_title,
                        "page_number": chunk.page_number,
                        "source_type": source_type,
                    },
                }
            )
            vector_records.append(
                VectorRecord(
                    id=vector_id,
                    vector=vector,
                    document=chunk.text,
                    metadata={
                        "user_id": user_id,
                        "document_id": doc_id,
                        "title": title,
                        "page_number": chunk.page_number,
                        "chunk_index": chunk.chunk_index,
                        "source_type": source_type,
                        "section_title": chunk.section_title,
                    },
                )
            )

        self.chunks.replace_for_document(doc_id, chunk_documents)
        stored = self.chunks.list_for_document(doc_id)
        id_by_index = {row.get("chunk_index"): str(row.get("_id")) for row in stored}
        for record in vector_records:
            record.metadata["chunk_id"] = id_by_index.get(
                record.metadata.get("chunk_index"), ""
            )

        upsert = vector_store.upsert(vector_records)
        if not upsert.ok:
            logger.error("Reindex vector upsert failed for %s: %s", doc_id, upsert.error)
            raise AppError(
                "The corrected chunks were stored but could not be indexed for search.",
                code="reindex_vector_failed",
                status_code=503,
                hint="Your correction is saved. Check VECTOR_DB, then retry reindexing.",
            )

        graph_counts = self._rebuild_graph(document)
        self.pages.clear_reindex_flag(doc_id)
        self.documents.update_fields(
            doc_id,
            {"chunk_count": len(chunks), "updated_at": utcnow()},
        )
        logger.info(
            "Reindexed document %s: %s chunks, %s concepts",
            doc_id,
            len(chunks),
            graph_counts["concepts"],
        )
        return {
            "document_id": doc_id,
            "chunk_count": len(chunks),
            "graph": graph_counts,
            "reindexed_at": utcnow(),
        }

    def _rebuild_graph(self, document: Dict[str, Any]) -> Dict[str, int]:
        """Rebuild this document's concepts/relations from effective text."""
        from db.study_repositories import ConceptRepository, RelationRepository
        from services.concept_extractor import (
            collect_candidates,
            extract_relations,
            filter_relations_to_labels,
        )

        user_id = str(document["user_id"])
        doc_id = str(document["_id"])
        title = document.get("title", "")

        concepts = ConceptRepository()
        relations_repo = RelationRepository()
        concepts.remove_document(user_id, doc_id)
        relations_repo.remove_document(user_id, doc_id)

        rows = self.pages.list_for_document(doc_id)
        page_pairs = [
            (row.get("page_number", 1), self.effective_text(row)) for row in rows
        ]
        candidates = collect_candidates(
            page_pairs,
            max_concepts=self.settings.graph_max_concepts_per_doc,
            min_score=self.settings.graph_min_concept_score,
        )
        if not candidates:
            return {"concepts": 0, "relations": 0}

        relations_list = extract_relations(
            page_pairs,
            candidates,
            max_relations_per_concept=self.settings.graph_max_relations_per_concept,
        )
        labels = [c.label for c in candidates]
        relations_list = filter_relations_to_labels(relations_list, labels)
        slug_by_label = {c.label: c.slug for c in candidates}

        for candidate in candidates:
            concepts.upsert(
                user_id=user_id,
                label=candidate.label,
                document_id=doc_id,
                document_title=title,
                page_numbers=candidate.pages or [1],
                occurrences=candidate.occurrences,
                score=candidate.score,
                definition=candidate.definition,
                snippets=candidate.snippets,
            )
        stored = 0
        for relation in relations_list:
            source_slug = slug_by_label.get(relation.source)
            target_slug = slug_by_label.get(relation.target)
            if not source_slug or not target_slug or source_slug == target_slug:
                continue
            relations_repo.upsert(
                user_id=user_id,
                source_slug=source_slug,
                target_slug=target_slug,
                relation=relation.relation,
                method=relation.method,
                weight=relation.weight,
                evidence={
                    "document_id": doc_id,
                    "document_title": title,
                    "page_number": relation.page_number,
                    "snippet": relation.snippet,
                    "confidence": relation.evidence_payload().get("confidence"),
                    "verification_status": relation.evidence_payload().get(
                        "verification_status"
                    ),
                },
            )
            stored += 1
        return {"concepts": len(candidates), "relations": stored}