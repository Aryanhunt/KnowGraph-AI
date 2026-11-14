"""
Document routes (``/api/documents``).

Covers upload, listing/filtering, page & chunk retrieval, metadata editing,
reprocessing and deletion. Every endpoint is guarded by ``require_auth`` and the
service scopes each query by the authenticated user.
"""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, request

from services.document_service import DocumentService
from utils.auth_middleware import current_user_id, json_body, pagination_args, require_auth
from utils.errors import ValidationError
from utils.files import SUPPORTED_EXTENSIONS
from utils.responses import created, ok, paginated

bp = Blueprint("documents", __name__, url_prefix="/api/documents")

UPLOAD_FIELDS = ("file", "document", "files")


def _parse_date(value):
    """Accept an ISO date or datetime from the filter UI."""
    if not value:
        return None
    raw = str(value).strip().replace("Z", "+00:00")
    for candidate in (raw, f"{raw}T00:00:00"):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _serialize_page(row) -> dict:
    """Compact page payload used by both page endpoints."""
    return {
        "page_number": row.get("page_number"),
        "text": row.get("text", ""),
        "ocr_used": row.get("ocr_used", False),
        "ocr_confidence": row.get("ocr_confidence"),
        "image_path": row.get("image_path"),
        "char_count": row.get("char_count", 0),
        "section_title": row.get("section_title", ""),
        # --- OCR quality pipeline -------------------------------------------
        "quality_label": row.get("quality_label", ""),
        "quality_metrics": row.get("quality_metrics") or {},
        "quality_warnings": row.get("quality_warnings") or [],
        "ocr_engine": row.get("ocr_engine", ""),
        "ocr_preprocessing": row.get("ocr_preprocessing") or {},
        "original_text": row.get("original_text", "") or row.get("text", ""),
        "corrected_text": row.get("corrected_text", ""),
        "correction_status": row.get("correction_status", ""),
        "needs_reindex": row.get("needs_reindex", False),
    }


@bp.post("")
@require_auth
def upload():
    """Upload one file (``multipart/form-data``) and start processing."""
    file_storage = next(
        (request.files.get(name) for name in UPLOAD_FIELDS if request.files.get(name) is not None),
        None,
    )
    if file_storage is None:
        raise ValidationError(
            "No file was received.",
            code="missing_file",
            hint=f"Send the file in a form field named '{UPLOAD_FIELDS[0]}'.",
            details={"supported_types": list(SUPPORTED_EXTENSIONS)},
        )

    service = DocumentService()
    document = service.create_from_upload(
        file_storage, current_user_id(), subject=str(request.form.get("subject", ""))
    )
    return created(
        service.serialize(document),
        meta={"status_url": f"/api/documents/{document['_id']}"},
    )


@bp.get("")
@require_auth
def list_documents():
    """List the user's documents with filters and pagination."""
    filters = {
        **pagination_args(),
        "status": request.args.get("status"),
        "subject": request.args.get("subject"),
        "tag": request.args.get("tag"),
        "document_type": request.args.get("document_type"),
        "search": request.args.get("search"),
        "date_from": _parse_date(request.args.get("date_from")),
        "date_to": _parse_date(request.args.get("date_to")),
    }
    result = DocumentService().list_documents(current_user_id(), filters)
    return paginated(
        result["documents"],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@bp.get("/queue")
@require_auth
def processing_queue():
    """Documents whose processing has not finished yet (progress panel)."""
    return ok(DocumentService().processing_queue(current_user_id()))


@bp.get("/subjects")
@require_auth
def subjects():
    return ok(DocumentService().subjects(current_user_id()))


@bp.get("/tags")
@require_auth
def tags():
    return ok(DocumentService().tags(current_user_id()))


@bp.get("/stats")
@require_auth
def stats():
    return ok(DocumentService().stats(current_user_id()))


@bp.get("/recent")
@require_auth
def recent():
    return ok(DocumentService().recent(current_user_id(), limit=int(request.args.get("limit", 5))))


@bp.get("/<document_id>")
@require_auth
def get_document(document_id: str):
    service = DocumentService()
    return ok(service.serialize(service.get_document(document_id, current_user_id())))


@bp.patch("/<document_id>")
@require_auth
def update_document(document_id: str):
    """Edit title, subject, tags, topics or summary."""
    service = DocumentService()
    document = service.update_document(document_id, current_user_id(), json_body())
    return ok(service.serialize(document))


@bp.delete("/<document_id>")
@require_auth
def delete_document(document_id: str):
    """Delete the document plus its pages, chunks, vectors and graph links."""
    return ok(DocumentService().delete_document(document_id, current_user_id()))


@bp.post("/<document_id>/reprocess")
@require_auth
def reprocess(document_id: str):
    """Re-run the pipeline (after installing OCR/Ollama, or following a failure)."""
    service = DocumentService()
    return ok(service.serialize(service.reprocess_document(document_id, current_user_id())))


@bp.get("/<document_id>/pages")
@require_auth
def pages(document_id: str):
    """All extracted pages, with OCR flags/confidence (brief §5)."""
    rows = DocumentService().get_pages(document_id, current_user_id())
    return ok([_serialize_page(row) for row in rows])


@bp.get("/<document_id>/pages/<int:page_number>")
@require_auth
def page(document_id: str, page_number: int):
    """One page — this is what a clicked citation opens (brief §7)."""
    row = DocumentService().get_page(document_id, page_number, current_user_id())
    return ok(_serialize_page(row))


@bp.get("/<document_id>/chunks")
@require_auth
def chunks(document_id: str):
    """Indexed chunks for a document — handy when checking retrieval quality."""
    limit = int(request.args.get("limit", 50))
    rows = DocumentService().get_chunks(document_id, current_user_id(), limit=limit)
    return ok(
        [
            {
                "chunk_index": row.get("chunk_index"),
                "page_number": row.get("page_number"),
                "text": row.get("text", ""),
                "source_type": row.get("source_type", ""),
                "embedding_id": row.get("embedding_id", ""),
                "char_count": row.get("char_count", 0),
            }
            for row in rows
        ]
    )


# ---------------------------------------------------------------------------
# OCR review & correction (quality pipeline)
# ---------------------------------------------------------------------------
from services.ocr_review_service import OcrReviewService  # noqa: E402


def _review_service() -> OcrReviewService:
    return OcrReviewService()


@bp.get("/<document_id>/ocr/review")
@require_auth
def ocr_review_pages(document_id: str):
    """All pages with OCR quality metadata + a review summary."""
    return ok(_review_service().list_pages(document_id, current_user_id()))


@bp.get("/<document_id>/ocr/review/<int:page_number>")
@require_auth
def ocr_review_page(document_id: str, page_number: int):
    """Quality report for one page."""
    return ok(_review_service().get_page_report(document_id, page_number, current_user_id()))


@bp.put("/<document_id>/ocr/review/<int:page_number>/correction")
@require_auth
def ocr_save_correction(document_id: str, page_number: int):
    """Save a user correction for one page (original OCR text is preserved)."""
    body = json_body()
    corrected = str(body.get("corrected_text", ""))
    mark_reviewed = bool(body.get("mark_reviewed", False))
    result = _review_service().save_correction(
        document_id, page_number, current_user_id(), corrected,
        mark_reviewed=mark_reviewed,
    )
    return ok(result)


@bp.delete("/<document_id>/ocr/review/<int:page_number>/correction")
@require_auth
def ocr_reset_correction(document_id: str, page_number: int):
    """Reset the correction back to the original OCR text."""
    return ok(_review_service().reset_correction(document_id, page_number, current_user_id()))


@bp.post("/<document_id>/ocr/review/<int:page_number>/review")
@require_auth
def ocr_mark_reviewed(document_id: str, page_number: int):
    """Mark a page as reviewed."""
    return ok(_review_service().mark_reviewed(document_id, page_number, current_user_id()))


@bp.post("/<document_id>/ocr/review/<int:page_number>/rerun")
@require_auth
def ocr_rerun_page(document_id: str, page_number: int):
    """Re-run OCR for one page using the preserved page image."""
    return ok(_review_service().rerun_page_ocr(document_id, page_number, current_user_id()))


@bp.post("/<document_id>/ocr/reindex")
@require_auth
def ocr_reindex(document_id: str):
    """Rebuild chunks/embeddings/graph from effective (corrected) page text."""
    body = json_body()
    rebuild_graph = bool(body.get("rebuild_graph", True))
    return ok(
        _review_service().reindex_document(
            document_id, current_user_id(), rebuild_graph=rebuild_graph
        )
    )