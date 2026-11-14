"""
Document processing pipeline (brief §4).

Implements exactly the stage order from the brief, and records progress after
every stage so the UI can show:

    Uploading... → Extracting text... → Running OCR... → Creating chunks...
    → Generating embeddings... → Extracting topics... → Building knowledge graph...
    → Completed

Two important behaviour rules:

* **Nothing is thrown away on failure.** Pages, OCR text and page images are
  stored before the embedding/graph stages run, so a failure late in the pipeline
  still leaves the extracted text available and the document can be reprocessed.
* **Failures are recorded, not raised at the caller.** The document gets
  ``processing_status=failed`` plus an actionable ``processing_error`` message
  (e.g. "Ollama is not running.") — the API request that queued it has already
  returned, so there is nobody left to raise to (brief §22).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config.settings import Settings, get_settings
from db.repositories import ChunkRepository, DocumentRepository, PageRepository
from db.study_repositories import ConceptRepository, RelationRepository
from models.domain import ProcessingStatus, utcnow
from models.graph import RELATION_TYPES
from services.chunking import TextChunk, chunk_pages
from services.concept_extractor import (
    collect_candidates,
    extract_relations,
    filter_relations_to_labels,
)
from services.embeddings.base import EmbeddingService
from services.embeddings.factory import get_embedding_service
from services.extraction.base import ExtractionResult
from services.extraction.registry import get_extractor
from services.llm import prompts
from services.llm.base import LLMService
from services.llm.factory import get_llm_service
from services.ocr.base import OCRService
from services.ocr.factory import get_ocr_service
from services.vector.base import VectorRecord
from services.vector.factory import get_vector_store
from utils.errors import AppError
from utils.logging_setup import get_logger
from utils.text import (
    clean_text,
    dedupe_preserving_order,
    detect_language,
    extractive_summary,
    keyword_scores,
)

logger = get_logger(__name__)

#: Text sample size sent to the LLM for metadata/graph extraction (keeps prompts
#: small enough for a 3B-class model and the configured context window).
METADATA_SAMPLE_CHARS = 6000
GRAPH_SAMPLE_CHARS = 4000

#: Words that suggest a research paper when scanning the first page.
_RESEARCH_MARKERS = ("abstract", "keywords", "doi", "et al", "references", "methodology",
                     "conclusion", "dataset", "proposed method")


class DocumentPipeline:
    """Runs a document through extraction → chunks → embeddings → graph."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        documents: Optional[DocumentRepository] = None,
        pages: Optional[PageRepository] = None,
        chunks: Optional[ChunkRepository] = None,
        concepts: Optional[ConceptRepository] = None,
        relations: Optional[RelationRepository] = None,
        ocr_service: Optional[OCRService] = None,
        embedding_service: Optional[EmbeddingService] = None,
        llm_service: Optional[LLMService] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.documents = documents or DocumentRepository()
        self.pages = pages or PageRepository()
        self.chunks = chunks or ChunkRepository()
        self.concepts = concepts or ConceptRepository()
        self.relations = relations or RelationRepository()

        # AI services are resolved lazily and defensively: a broken vector store
        # must not stop the pipeline from storing extracted text.
        self._ocr_service = ocr_service
        self._embedding_service = embedding_service
        self._llm_service = llm_service
        self._vector_store = None

    # ------------------------------------------------------------------
    # Service accessors (lazy, with graceful failure)
    # ------------------------------------------------------------------
    @property
    def ocr_service(self) -> OCRService:
        if self._ocr_service is None:
            self._ocr_service = get_ocr_service(self.settings)
        return self._ocr_service

    @property
    def embedding_service(self) -> EmbeddingService:
        if self._embedding_service is None:
            self._embedding_service = get_embedding_service(self.settings)
        return self._embedding_service

    @property
    def llm_service(self) -> LLMService:
        if self._llm_service is None:
            self._llm_service = get_llm_service(self.settings)
        return self._llm_service

    @property
    def vector_store(self):
        if self._vector_store is None:
            self._vector_store = get_vector_store(self.settings)
        return self._vector_store

    # ------------------------------------------------------------------
    # Progress helpers
    # ------------------------------------------------------------------
    def _set_stage(self, document_id: str, status: str) -> None:
        """Record the current stage (and its progress fraction) on the document."""
        self.documents.update_fields(
            document_id,
            {
                "processing_status": status,
                "current_stage": status,
                "progress": ProcessingStatus.progress_for(status),
                "processing_error": None,
            },
        )
        logger.info("Document %s → %s", document_id, ProcessingStatus.label_for(status))

    def _fail(self, document_id: str, message: str) -> None:
        self.documents.update_status(document_id, ProcessingStatus.FAILED, error=message)

    # ------------------------------------------------------------------
    # Stage 1-4: extraction (digital text, automatic OCR fallback)
    # ------------------------------------------------------------------
    def _stage_extract(self, document: Dict[str, Any]) -> ExtractionResult:
        document_id = str(document["_id"])
        extension = document.get("file_type", "")
        extractor = get_extractor(
            extension, ocr_service=self.ocr_service, settings=self.settings
        )

        # Extractors already clean the text they produce, so the cleaning stage is
        # reported here instead of being duplicated.
        self._set_stage(document_id, ProcessingStatus.EXTRACTING)
        result = extractor.extract(
            path=Path(document["file_path"]),
            document_id=document_id,
            document_title=document.get("title", ""),
            page_image_dir=self.settings.page_image_dir,
        )
        if result.ocr_page_count:
            self._set_stage(document_id, ProcessingStatus.RUNNING_OCR)
        self._set_stage(document_id, ProcessingStatus.CLEANING)

        if not result.has_content:
            message = "; ".join(result.warnings) or (
                "No readable text could be extracted from this file. If it is a scan, "
                "install Tesseract (OCR_ENGINE=tesseract) and reprocess."
            )
            raise AppError(
                message,
                code="no_text_extracted",
                status_code=422,
                hint="Use a supported file, or reprocess after installing/enabling OCR.",
            )
        return result

    # ------------------------------------------------------------------
    # Stage 4: store pages (preserving page numbers and OCR evidence)
    # ------------------------------------------------------------------
    def _stage_pages(
        self, document: Dict[str, Any], result: ExtractionResult
    ) -> List[Dict[str, Any]]:
        document_id = str(document["_id"])
        user_id = str(document["user_id"])

        page_documents = [
            {
                "document_id": document_id,
                "user_id": user_id,
                "page_number": page.page_number,
                "text": clean_text(page.text),
                "ocr_used": page.ocr_used,
                "ocr_confidence": page.ocr_confidence,
                "image_path": page.image_path,
                "char_count": page.char_count,
                "section_title": page.section_title or "",
                # --- OCR quality pipeline --------------------------------
                "original_text": clean_text(page.text),
                "corrected_text": "",
                "correction_status": "",
                "correction_version": 0,
                "needs_reindex": False,
                "quality_label": page.quality_label or "",
                "quality_metrics": page.quality_metrics or {},
                "quality_warnings": page.quality_warnings or [],
                "ocr_engine": page.ocr_engine or "",
                "ocr_preprocessing": page.ocr_preprocessing or {},
                "ocr_run_at": utcnow() if page.ocr_used else None,
                "created_at": utcnow(),
            }
            for page in result.pages
        ]
        self.pages.replace_for_document(document_id, page_documents)
        logger.info("Stored %s pages for document %s", len(page_documents), document_id)
        return page_documents

    # ------------------------------------------------------------------
    # Stage 5: chunking
    # ------------------------------------------------------------------
    def _stage_chunks(self, page_documents: Sequence[Dict[str, Any]]) -> List[TextChunk]:
        class _PageView:
            """Adapter so the chunker can consume stored page dicts."""

            def __init__(self, payload: Dict[str, Any]) -> None:
                self.page_number = payload.get("page_number", 1)
                self.text = payload.get("text", "")
                self.section_title = payload.get("section_title", "")

        chunks = chunk_pages(
            [_PageView(payload) for payload in page_documents],
            chunk_size=self.settings.chunk_size,
            overlap=self.settings.chunk_overlap,
        )
        return [chunk for chunk in chunks if chunk.text.strip()]

    # ------------------------------------------------------------------
    # Stage 6-7: embeddings + vector index
    # ------------------------------------------------------------------
    def _stage_index(
        self, document: Dict[str, Any], chunks: Sequence[TextChunk], source_type: str
    ) -> List[Dict[str, Any]]:
        document_id = str(document["_id"])
        user_id = str(document["user_id"])
        title = document.get("title", "")

        self._set_stage(document_id, ProcessingStatus.CHUNKING)
        if not chunks:
            raise AppError("No text chunks could be created from this document.", code="no_chunks")

        self._set_stage(document_id, ProcessingStatus.EMBEDDING)
        texts = [chunk.text for chunk in chunks]
        embedding_result = self.embedding_service.embed_texts(texts)
        if not embedding_result.ok or len(embedding_result.vectors) != len(texts):
            # Vectors from different models are not comparable, so a different
            # model is never substituted silently — this is a hard failure with
            # an actionable hint instead of a corrupted index.
            reason = embedding_result.error or "The embedding model did not return vectors."
            raise AppError(
                f"Embeddings could not be generated. {reason}",
                code="embedding_failed",
                status_code=503,
                hint=(
                    "Check that Ollama is running and the embedding model is installed "
                    "(`ollama pull <EMBEDDING_MODEL>`), then reprocess the document."
                ),
            )

        chunk_documents: List[Dict[str, Any]] = []
        vector_records: List[VectorRecord] = []
        for chunk, vector in zip(chunks, embedding_result.vectors):
            vector_id = f"{document_id}:{chunk.chunk_index}"
            chunk_documents.append(
                {
                    "document_id": document_id,
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
                    "created_at": utcnow(),
                }
            )
            vector_records.append(
                VectorRecord(
                    id=vector_id,
                    vector=vector,
                    document=chunk.text,
                    metadata={
                        "user_id": user_id,
                        "document_id": document_id,
                        "title": title,
                        "page_number": chunk.page_number,
                        "chunk_index": chunk.chunk_index,
                        "source_type": source_type,
                        "section_title": chunk.section_title,
                    },
                )
            )

        # Store the chunk rows first so vector metadata can carry the Mongo id.
        self.chunks.replace_for_document(document_id, chunk_documents)
        stored = self.chunks.list_for_document(document_id)
        id_by_index = {row.get("chunk_index"): str(row.get("_id")) for row in stored}
        for record in vector_records:
            record.metadata["chunk_id"] = id_by_index.get(record.metadata.get("chunk_index"), "")

        upsert_result = self.vector_store.upsert(vector_records)
        if not upsert_result.ok:
            raise AppError(
                ("The chunks were stored but could not be indexed for semantic search. "
                 f"{upsert_result.error or ''}").strip(),
                code="vector_upsert_failed",
                status_code=503,
                hint="Check the vector database configuration (VECTOR_DB), then reprocess.",
            )

        logger.info(
            "Indexed %s chunks for document %s using %s",
            len(vector_records),
            document_id,
            embedding_result.model or self.embedding_service.model,
        )
        return chunk_documents

    # ------------------------------------------------------------------
    # Stage 8: LLM metadata extraction (with a deterministic fallback)
    # ------------------------------------------------------------------
    def _stage_metadata(
        self, document: Dict[str, Any], result: ExtractionResult
    ) -> Dict[str, Any]:
        document_id = str(document["_id"])
        self._set_stage(document_id, ProcessingStatus.EXTRACTING_TOPICS)

        full_text = result.full_text()
        sample = full_text[:METADATA_SAMPLE_CHARS]

        # --- try the local LLM first -------------------------------------
        if self.llm_service.is_available():
            payload = self.llm_service.generate_json(
                prompts.build_metadata_prompt(document.get("title", ""), sample),
                system=prompts.METADATA_SYSTEM,
                max_tokens=700,
            )
            if payload and str(payload.get("summary", "") or "").strip():
                return {
                    "summary": str(payload.get("summary", "")).strip()[:2000],
                    "tags": _clean_list(payload.get("tags"), limit=20, lowercase=True),
                    "topics": _clean_list(payload.get("topics"), limit=20),
                    "subject": str(payload.get("subject", "") or "").strip()[:120],
                    "is_research_paper": bool(payload.get("is_research_paper", False)),
                    "summary_method": "llm",
                    "language": detect_language(full_text) or "unknown",
                }

        # --- deterministic fallback (the document is never left without info) ---
        keywords = [word for word, _count in keyword_scores(full_text, top_n=15)]
        return {
            "summary": extractive_summary(full_text, max_sentences=4, max_chars=900),
            "tags": keywords[:10],
            "topics": keywords[:8],
            "subject": "",
            "is_research_paper": _looks_like_research_paper(full_text[:4000]),
            # Honest labelling: the UI shows "extractive" rather than pretending the
            # summary came from the model (brief §11/§15).
            "summary_method": "extractive",
            "language": detect_language(full_text) or "unknown",
        }

    # ------------------------------------------------------------------
    # Stage 9: knowledge graph extraction
    # ------------------------------------------------------------------
    def _stage_graph(
        self, document: Dict[str, Any], page_documents: Sequence[Dict[str, Any]]
    ) -> Dict[str, int]:
        document_id = str(document["_id"])
        user_id = str(document["user_id"])
        title = document.get("title", "")
        self._set_stage(document_id, ProcessingStatus.BUILDING_GRAPH)

        # Rebuild this document's part of the graph from scratch. Without this, a
        # reprocess *added* to the previous run (occurrence counts and page
        # references doubled) and concepts that improved extraction no longer
        # produces — "job job", "Gemini Notebook" — stayed in the graph forever.
        self.concepts.remove_document(user_id, document_id)
        self.relations.remove_document(user_id, document_id)

        page_pairs: List[Tuple[int, str]] = [
            (int(payload.get("page_number", 1)), payload.get("text", ""))
            for payload in page_documents
        ]
        candidates = collect_candidates(
            page_pairs,
            max_concepts=self.settings.graph_max_concepts_per_doc,
            min_score=self.settings.graph_min_concept_score,
        )
        if not candidates:
            logger.info("No concepts extracted for document %s", document_id)
            return {"concepts": 0, "relations": 0}

        relations = extract_relations(
            page_pairs,
            candidates,
            max_relations_per_concept=self.settings.graph_max_relations_per_concept,
        )

        # The local model may *add* typed relations, but the deterministic pass above
        # already built the graph, so an unavailable model changes nothing important
        # (brief §9: do not rely entirely on the LLM).
        if self.llm_service.is_available():
            relations = self._merge_llm_relations(page_pairs, candidates, relations)

        labels = [candidate.label for candidate in candidates]
        relations = filter_relations_to_labels(relations, labels)
        slug_by_label = {candidate.label: candidate.slug for candidate in candidates}

        stored_concepts = 0
        for candidate in candidates:
            self.concepts.upsert(
                user_id=user_id,
                label=candidate.label,
                document_id=document_id,
                document_title=title,
                page_numbers=candidate.pages or [1],
                occurrences=candidate.occurrences,
                score=candidate.score,
                definition=candidate.definition,
                snippets=candidate.snippets,
            )
            stored_concepts += 1

        stored_relations = 0
        for relation in relations:
            source_slug = slug_by_label.get(relation.source)
            target_slug = slug_by_label.get(relation.target)
            if not source_slug or not target_slug or source_slug == target_slug:
                continue
            evidence = relation.evidence_payload()
            evidence.update(
                {
                    "document_id": document_id,
                    "document_title": title,
                }
            )
            self.relations.upsert(
                user_id=user_id,
                source_slug=source_slug,
                target_slug=target_slug,
                relation=relation.relation,
                method=relation.method,
                weight=relation.weight,
                evidence=evidence,
                confidence=evidence.get("confidence"),
                verification_status=evidence.get("verification_status"),
            )
            stored_relations += 1

        logger.info(
            "Graph for %s: %s concepts, %s relations",
            document_id,
            stored_concepts,
            stored_relations,
        )
        return {"concepts": stored_concepts, "relations": stored_relations}

    def _merge_llm_relations(
        self,
        page_pairs: Sequence[Tuple[int, str]],
        candidates: Sequence[Any],
        relations: List[Any],
    ) -> List[Any]:
        """Ask the local model to type relationships between the extracted concepts."""
        from services.concept_extractor import RelationCandidate   # local import: avoids a cycle

        sample = "\n".join(text for _page, text in page_pairs)[:GRAPH_SAMPLE_CHARS]
        labels = [candidate.label for candidate in candidates][:30]
        payload = self.llm_service.generate_json(
            prompts.build_graph_prompt(sample, labels),
            system=prompts.GRAPH_SYSTEM,
            max_tokens=700,
        )
        if not payload:
            return relations

        existing = {(item.source.lower(), item.target.lower()) for item in relations}
        label_lookup = {label.lower(): label for label in labels}

        for item in payload.get("relations", []) or []:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source", "")).strip()
            target = str(item.get("target", "")).strip()
            relation = str(item.get("relation", "related_to")).strip().lower()
            if relation not in RELATION_TYPES:
                relation = "related_to"
            if not source or not target:
                continue
            if source.lower() not in label_lookup or target.lower() not in label_lookup:
                # The model must stay inside the concept list we provided.
                continue
            if (source.lower(), target.lower()) in existing:
                continue
            if relation == "related_to":
                continue        # co-occurrence already covers the generic case
            existing.add((source.lower(), target.lower()))
            relations.append(
                RelationCandidate(
                    source=label_lookup[source.lower()],
                    target=label_lookup[target.lower()],
                    relation=relation,
                    method="llm",
                    weight=1.5,
                    page_number=None,
                    snippet="Typed by the local model from the extracted concepts.",
                )
            )
        return relations

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------
    def run(self, document_id: str, user_id: str) -> Dict[str, Any]:
        """Run every stage for one document and record the outcome."""
        document = self.documents.find_for_user(document_id, user_id)
        if not document:
            logger.warning("Processing requested for a missing document: %s", document_id)
            return {"document_id": document_id, "status": "missing"}

        try:
            result = self._stage_extract(document)
            page_documents = self._stage_pages(document, result)
            chunks = self._stage_chunks(page_documents)
            self._stage_index(document, chunks, result.source_type)
            metadata = self._stage_metadata(document, result)
            graph = self._stage_graph(document, page_documents)

            # A subject the user typed in the upload form always wins over the guess.
            subject = (document.get("subject") or "").strip() or metadata.get("subject", "")

            self.documents.update_fields(
                document_id,
                {
                    "page_count": result.page_count,
                    "chunk_count": len(chunks),
                    "ocr_used": result.ocr_used,
                    "ocr_page_count": result.ocr_page_count,
                    "language": metadata.get("language", "unknown"),
                    "summary": metadata.get("summary", ""),
                    "summary_method": metadata.get("summary_method", ""),
                    "tags": metadata.get("tags", []),
                    "topics": metadata.get("topics", []),
                    "subject": subject,
                    "is_research_paper": bool(metadata.get("is_research_paper", False)),
                    "char_count": result.char_count,
                    "embedding_model": self.embedding_service.model,
                    "processing_error": None,
                    "extraction": {
                        "method": result.method,
                        "source_type": result.source_type,
                        "average_ocr_confidence": result.average_ocr_confidence(),
                        "warnings": result.warnings,
                        "metadata": result.metadata,
                    },
                },
            )
            self.documents.update_status(document_id, ProcessingStatus.READY)

            logger.info(
                "Document %s is ready (%s pages, %s chunks, %s concepts)",
                document_id,
                result.page_count,
                len(chunks),
                graph.get("concepts", 0),
            )
            return {
                "document_id": document_id,
                "status": ProcessingStatus.READY,
                "page_count": result.page_count,
                "chunk_count": len(chunks),
                "ocr_used": result.ocr_used,
                "concepts": graph.get("concepts", 0),
                "relations": graph.get("relations", 0),
                "warnings": result.warnings,
            }

        except AppError as exc:
            message = exc.message if not exc.hint else f"{exc.message} {exc.hint}"
            logger.error("Processing failed for %s: %s", document_id, message)
            self._fail(document_id, message)
            return {"document_id": document_id, "status": ProcessingStatus.FAILED, "error": message}

        except Exception as exc:  # noqa: BLE001 - never let a background job die silently
            logger.exception("Unexpected processing error for %s", document_id)
            self._fail(
                document_id,
                f"Processing failed unexpectedly: {exc}. "
                "Check backend/logs/app.log and try reprocessing the document.",
            )
            return {
                "document_id": document_id,
                "status": ProcessingStatus.FAILED,
                "error": str(exc),
            }


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------
def _clean_list(value: Any, *, limit: int = 20, lowercase: bool = False) -> List[str]:
    """Normalise a list coming from the LLM (strings, comma separated or list)."""
    if value is None:
        return []
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value]
    else:
        items = [str(value).strip()]

    cleaned = [item for item in items if item]
    if lowercase:
        cleaned = [item.lower() for item in cleaned]
    return dedupe_preserving_order(cleaned)[:limit]


def _looks_like_research_paper(text_sample: str) -> bool:
    """Heuristic research-paper detection used when the LLM is unavailable."""
    lowered = (text_sample or "").lower()
    hits = sum(1 for marker in _RESEARCH_MARKERS if marker in lowered)
    return hits >= 3


def process_document(document_id: str, user_id: str, settings: Optional[Settings] = None) -> Dict[str, Any]:
    """
    Entry point used by the background queue (and by tests).

    Kept as a module-level function so it can be submitted to the thread pool
    without holding on to a service instance.
    """
    pipeline = DocumentPipeline(settings)
    return pipeline.run(str(document_id), str(user_id))