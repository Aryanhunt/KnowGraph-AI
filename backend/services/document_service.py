"""
Document service — upload, listing, retrieval and deletion (brief §4, §5, §21).

Responsibilities:

* validate an upload against the allowed types and size limit,
* store the binary on disk (never inside MongoDB) under ``storage/uploads/<user>/``,
* create the ``documents`` record and queue the processing pipeline,
* expose per-user CRUD used by the routes,
* delete a document completely: file, pages, chunks, vectors, graph links and
  generated study material.

Every method takes ``user_id`` and scopes its query with it, so one user can never
read or delete another user's data.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from config.settings import Settings, get_settings
from db.repositories import ChunkRepository, DocumentRepository, PageRepository
from db.study_repositories import (
    ConceptRepository,
    FlashcardRepository,
    QuizRepository,
    RelationRepository,
    StudyEventRepository,
)
from models.domain import ProcessingStatus, utcnow
from services.jobs import run_in_background
from utils.errors import NotFoundError, ValidationError
from utils.files import detect_mime_type, human_size, sha256_of_file, validate_upload
from utils.logging_setup import get_logger
from utils.security import safe_remove
from services.relationship_parser import RelationshipParser

logger = get_logger(__name__)


def _title_from_filename(filename: str) -> str:
    """Human-friendly default title: ``DBMS-Unit3-notes.pdf`` → ``DBMS Unit3 notes``."""
    stem = filename.rsplit(".", 1)[0]
    pretty = stem.replace("_", " ").replace("-", " ").strip()
    return (pretty or "Untitled document")[:180]


class DocumentService:
    """Application logic for uploaded documents."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        documents: Optional[DocumentRepository] = None,
        pages: Optional[PageRepository] = None,
        chunks: Optional[ChunkRepository] = None,
        concepts: Optional[ConceptRepository] = None,
        relations: Optional[RelationRepository] = None,
        flashcards: Optional[FlashcardRepository] = None,
        quizzes: Optional[QuizRepository] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.documents = documents or DocumentRepository()
        self.pages = pages or PageRepository()
        self.chunks = chunks or ChunkRepository()
        self.concepts = concepts or ConceptRepository()
        self.relations = relations or RelationRepository()
        self.flashcards = flashcards or FlashcardRepository()
        self.quizzes = quizzes or QuizRepository()

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------
    def create_from_upload(
        self, file_storage, user_id: Any, *, subject: str = ""
    ) -> Dict[str, Any]:
        """
        Persist an uploaded file and queue its processing.

        ``file_storage`` is a Werkzeug ``FileStorage`` (Flask's ``request.files``).
        """
        self.settings.ensure_directories()
        original_filename = getattr(file_storage, "filename", "") or ""
        declared_mime = getattr(file_storage, "mimetype", "") or ""

        # Determine the size without loading the whole file into memory.
        stream = file_storage.stream
        position = stream.tell() if hasattr(stream, "tell") else 0
        stream.seek(0, 2)
        size_bytes = stream.tell()
        stream.seek(position)

        info = validate_upload(
            original_filename=original_filename,
            size_bytes=size_bytes,
            declared_mime=declared_mime,
            upload_dir=self.settings.upload_dir,
            user_id=str(user_id),
            max_upload_mb=self.settings.max_upload_mb,
        )

        try:
            stream.seek(0)
            file_storage.save(str(info.stored_path))
        except OSError as exc:
            raise ValidationError(
                f"The file could not be saved: {exc}",
                code="storage_write_failed",
                hint="Check that the storage directory is writable.",
            ) from exc

        stored_size = info.stored_path.stat().st_size
        if stored_size == 0:
            safe_remove(info.stored_path, allowed_root=self.settings.upload_dir)
            raise ValidationError("The uploaded file is empty.")

        # Duplicate detection is informative, not blocking: re-uploading the same
        # file is allowed (a student may want it counted under another subject).
        file_hash = sha256_of_file(info.stored_path)
        duplicate = self.documents.find_by_hash(user_id, file_hash)

        document = {
            "user_id": str(user_id),
            "title": _title_from_filename(info.safe_filename),
            "original_filename": info.safe_filename,
            "file_path": str(info.stored_path),
            "file_type": info.extension,
            "mime_type": detect_mime_type(info.stored_path, info.declared_mime),
            "file_size": stored_size,
            "file_hash": file_hash,
            "subject": subject.strip(),
            "processing_status": ProcessingStatus.QUEUED,
            "current_stage": ProcessingStatus.QUEUED,
            "progress": ProcessingStatus.progress_for(ProcessingStatus.QUEUED),
            "ocr_used": False,
            "page_count": 0,
            "chunk_count": 0,
            "upload_date": utcnow(),
        }
        document_id = self.documents.create(document)

        logger.info(
            "Queued document %s (%s, %s)", document_id, info.safe_filename, human_size(stored_size)
        )
        self.queue_processing(document_id, user_id)

        created = self.documents.find_for_user(document_id, user_id) or {}
        created["duplicate_of"] = str(duplicate["_id"]) if duplicate else None
        return created

    def queue_processing(self, document_id: Any, user_id: Any) -> None:
        """Send the document through the pipeline (background or inline)."""
        # Imported here to avoid a circular import (the pipeline uses repositories).
        from services.pipeline import process_document

        run_in_background(process_document, str(document_id), str(user_id))

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def list_documents(self, user_id: Any, filters: Dict[str, Any]) -> Dict[str, Any]:
        documents, total, page, page_size = self.documents.list_for_user(
            user_id,
            page=int(filters.get("page") or 1),
            page_size=int(filters.get("page_size") or 20),
            status=filters.get("status"),
            subject=filters.get("subject"),
            tag=filters.get("tag"),
            document_type=filters.get("document_type"),
            search=filters.get("search"),
            date_from=filters.get("date_from"),
            date_to=filters.get("date_to"),
        )
        return {
            "documents": [self.serialize(document) for document in documents],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get_document(self, document_id: Any, user_id: Any) -> Dict[str, Any]:
        document = self.documents.find_for_user(document_id, user_id)
        if not document:
            raise NotFoundError("Document not found.", code="document_not_found")
        return document

    def get_pages(self, document_id: Any, user_id: Any) -> List[Dict[str, Any]]:
        self.get_document(document_id, user_id)      # ownership check first
        return self.pages.list_for_document(document_id)

    def get_page(self, document_id: Any, page_number: int, user_id: Any) -> Dict[str, Any]:
        self.get_document(document_id, user_id)
        page = self.pages.get_page(document_id, page_number)
        if not page:
            raise NotFoundError(
                f"Page {page_number} was not found in this document.", code="page_not_found"
            )
        return page

    def get_chunks(self, document_id: Any, user_id: Any, *, limit: int = 0) -> List[Dict[str, Any]]:
        self.get_document(document_id, user_id)
        return self.chunks.list_for_document(document_id, limit=limit)

    def subjects(self, user_id: Any) -> List[Dict[str, Any]]:
        return self.documents.subjects(user_id)

    def tags(self, user_id: Any) -> List[Dict[str, Any]]:
        return self.documents.tags(user_id)

    def stats(self, user_id: Any) -> Dict[str, Any]:
        return self.documents.stats(user_id)

    def recent(self, user_id: Any, limit: int = 5) -> List[Dict[str, Any]]:
        return [self.serialize(document) for document in self.documents.recent(user_id, limit)]

    def processing_queue(self, user_id: Any) -> List[Dict[str, Any]]:
        """Documents still being processed (drives the progress panel)."""
        documents, _total, _page, _size = self.documents.list_for_user(
            user_id, page=1, page_size=20
        )
        return [
            self.serialize(document)
            for document in documents
            if document.get("processing_status") not in ProcessingStatus.TERMINAL
        ]

    def serialize(self, document: Dict[str, Any]) -> Dict[str, Any]:
        """
        Shape a document for the API.

        Adds the derived presentation fields the UI needs (status label, progress
        percentage, human size, page/chunk counts, processing warnings) so the
        frontend never has to re-implement them.
        """
        status = document.get("processing_status", ProcessingStatus.QUEUED)
        payload = {
            "id": str(document.get("_id")),
            "title": document.get("title", ""),
            "original_filename": document.get("original_filename", ""),
            "file_type": document.get("file_type", ""),
            "mime_type": document.get("mime_type", ""),
            "file_size": document.get("file_size", 0),
            "file_size_label": human_size(int(document.get("file_size", 0) or 0)),
            "upload_date": document.get("upload_date"),
            "created_at": document.get("created_at"),
            "processing_status": status,
            "current_stage": document.get("current_stage", status),
            "stage_label": ProcessingStatus.label_for(document.get("current_stage", status)),
            "progress": document.get("progress", 0.0),
            "processing_error": document.get("processing_error"),
            "page_count": document.get("page_count", 0),
            "chunk_count": document.get("chunk_count", 0),
            "ocr_used": document.get("ocr_used", False),
            "ocr_page_count": document.get("ocr_page_count", 0),
            "language": document.get("language", "unknown"),
            "summary": document.get("summary", ""),
            "summary_method": document.get("summary_method", ""),
            "tags": document.get("tags", []),
            "topics": document.get("topics", []),
            "subject": document.get("subject", ""),
            "is_research_paper": document.get("is_research_paper", False),
            "char_count": document.get("char_count", 0),
            "embedding_model": document.get("embedding_model", ""),
        }
        if "duplicate_of" in document:
            payload["duplicate_of"] = document["duplicate_of"]
        return payload

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def update_document(self, document_id: Any, user_id: Any, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Update user-editable metadata (title, subject, tags, topics)."""
        document = self.get_document(document_id, user_id)

        allowed = {
            "title": str,
            "subject": str,
            "summary": str,
            "is_research_paper": bool,
        }
        payload: Dict[str, Any] = {}
        for key, caster in allowed.items():
            if key in fields and fields[key] is not None:
                payload[key] = caster(fields[key])

        for list_key in ("tags", "topics"):
            if list_key in fields and fields[list_key] is not None:
                values = fields[list_key]
                if isinstance(values, str):
                    values = [item.strip() for item in values.split(",") if item.strip()]
                payload[list_key] = [str(item).strip() for item in values if str(item).strip()][:30]

        if not payload:
            return document

        self.documents.update_fields(document_id, payload)
        return self.get_document(document_id, user_id)

    def delete_document(self, document_id: Any, user_id: Any) -> Dict[str, Any]:
        """
        Remove a document and everything derived from it.

        Order matters: derived data first (vectors, chunks, pages, graph links,
        flashcards), then the file on disk, then the MongoDB record.
        """
        document = self.get_document(document_id, user_id)
        identifier = str(document["_id"])

        removed = {
            "vectors": 0,
            "chunks": 0,
            "pages": 0,
            "concepts": 0,
            "relations": 0,
            "flashcards": 0,
            "quizzes": 0,
            "file_removed": False,
        }

        # --- vector store -------------------------------------------------
        try:
            from services.vector.factory import get_vector_store

            removed["vectors"] = get_vector_store(self.settings).delete_document(identifier)
        except Exception as exc:  # noqa: BLE001 - deletion must continue regardless
            logger.warning("Could not delete vectors for %s: %s", identifier, exc)

        # --- mongo collections -------------------------------------------
        removed["chunks"] = self.chunks.delete_for_document(identifier)
        removed["pages"] = self.pages.delete_for_document(identifier)
        concept_result = self.concepts.remove_document(user_id, identifier)
        removed["concepts"] = int(concept_result.get("deleted", 0))
        removed["relations"] = self.relations.remove_document(user_id, identifier)
        removed["flashcards"] = self.flashcards.delete_for_documents(user_id, [identifier])
        removed["quizzes"] = self.quizzes.delete_for_documents(user_id, [identifier])
        removed["study_events"] = StudyEventRepository().delete_for_documents(user_id, [identifier])

        # --- file on disk -------------------------------------------------
        file_path = document.get("file_path")
        if file_path:
            removed["file_removed"] = safe_remove(
                file_path, allowed_root=self.settings.storage_dir
            )

        # --- page renders -------------------------------------------------
        page_dir = self.settings.page_image_dir / identifier
        if page_dir.exists():
            for image in page_dir.glob("*.png"):
                safe_remove(image, allowed_root=self.settings.page_image_dir)
            try:
                page_dir.rmdir()
            except OSError:  # pragma: no cover - non-empty directory
                pass

        self.documents.delete(document_id, user_id)
        logger.info("Deleted document %s (%s)", identifier, removed)
        return {"id": identifier, "title": document.get("title", ""), "removed": removed}

    def reprocess_document(self, document_id: Any, user_id: Any) -> Dict[str, Any]:
        """Re-run the pipeline for a document (useful after a failure or a model change)."""
        document = self.get_document(document_id, user_id)
        identifier = str(document["_id"])

        # Clear previous derived data so reprocessing is idempotent.
        try:
            from services.vector.factory import get_vector_store

            get_vector_store(self.settings).delete_document(identifier)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not clear vectors before reprocessing %s: %s", identifier, exc)

        self.chunks.delete_for_document(identifier)
        self.pages.delete_for_document(identifier)
        self.concepts.remove_document(user_id, identifier)
        self.relations.remove_document(user_id, identifier)
        # Study material was built from the *old* extraction, so it is cleared
        # as well; otherwise a reprocessed document keeps quizzes/flashcards
        # that no longer match its text.
        self.flashcards.delete_for_documents(user_id, [identifier])
        self.quizzes.delete_for_documents(user_id, [identifier])

        self.documents.update_fields(
            identifier,
            {
                "processing_status": ProcessingStatus.QUEUED,
                "current_stage": ProcessingStatus.QUEUED,
                "progress": ProcessingStatus.progress_for(ProcessingStatus.QUEUED),
                "processing_error": None,
            },
        )
        self.queue_processing(identifier, user_id)
        return self.get_document(identifier, user_id)