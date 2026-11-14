"""
Search routes (``/api/search``).

Exposes global search (semantic / keyword / hybrid), page-level search and the
recorded search history. The relevance band shown to the user is derived from the
actual retrieval score using documented thresholds — never invented (brief §15).
"""

from __future__ import annotations

from flask import Blueprint, request

from services.search_service import SearchService
from utils.auth_middleware import current_user_id, json_body, require_auth
from utils.errors import ValidationError
from utils.responses import ok

bp = Blueprint("search", __name__, url_prefix="/api/search")

#: Hybrid RRF scores cluster tightly, so the bands are documented here.
BAND_HIGH = 0.020
BAND_MEDIUM = 0.010


def relevance_band(score) -> str:
    """Convert a real retrieval score into High / Medium / Low."""
    if score is None:
        return "Unknown"
    if score >= BAND_HIGH:
        return "High"
    if score >= BAND_MEDIUM:
        return "Medium"
    return "Low"


def _serialize_result(result) -> dict:
    payload = result.to_dict()
    payload["relevance"] = relevance_band(result.score)
    return payload


@bp.post("")
@require_auth
def search():
    """
    Run a search across the user's documents.

    Body: ``{"query": "...", "mode": "hybrid|semantic|keyword",
    "document_ids": [...], "subject": "...", "top_k": 6}``
    """
    payload = json_body()
    query = str(payload.get("query", "")).strip()
    if not query:
        raise ValidationError("Please enter something to search for.", code="empty_query")

    mode = str(payload.get("mode", "hybrid")).lower()
    if mode not in ("hybrid", "semantic", "keyword"):
        raise ValidationError(
            f"Unknown search mode '{mode}'.",
            hint="Use hybrid, semantic or keyword.",
        )

    service = SearchService()
    results = service.search(
        current_user_id(),
        query,
        mode=mode,
        document_ids=payload.get("document_ids") or None,
        subject=payload.get("subject") or None,
        top_k=int(payload.get("top_k") or 0) or None,
    )
    return ok(
        [_serialize_result(result) for result in results],
        meta={
            "query": query,
            "mode": mode,
            "result_count": len(results),
            "score_meaning": (
                "Reciprocal Rank Fusion score from semantic + keyword ranking"
                if mode == "hybrid"
                else "Cosine similarity from the vector index"
                if mode == "semantic"
                else "MongoDB text-search score"
            ),
            "bands": {"high": BAND_HIGH, "medium": BAND_MEDIUM},
        },
    )


@bp.get("/pages")
@require_auth
def search_pages():
    """Search inside page text (optionally within one document)."""
    query = request.args.get("q", "").strip()
    if not query:
        raise ValidationError("Please provide a query using ?q=", code="empty_query")
    document_id = request.args.get("document_id")
    rows = SearchService().search_pages(
        current_user_id(),
        query,
        document_ids=[document_id] if document_id else None,
        limit=int(request.args.get("limit", 20)),
    )
    return ok(
        [
            {
                "document_id": row.get("document_id"),
                "page_number": row.get("page_number"),
                "snippet": (row.get("text") or "")[:400],
                "ocr_used": row.get("ocr_used", False),
                "section_title": row.get("section_title", ""),
            }
            for row in rows
        ],
        meta={"query": query, "result_count": len(rows), "match_type": "literal page text"},
    )


@bp.get("/history")
@require_auth
def history():
    """The user's most recent searches (used by the search page and analytics)."""
    from db.study_repositories import SearchLogRepository

    rows = SearchLogRepository().list_for_user(current_user_id(), limit=25)
    return ok(
        [
            {
                "query": row.get("query"),
                "mode": row.get("mode"),
                "result_count": row.get("result_count"),
                "created_at": row.get("created_at"),
            }
            for row in rows
        ]
    )