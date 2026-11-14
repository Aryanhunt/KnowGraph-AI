"""
Chat routes (``/api/chat``).

Implements the five chat modes from brief §8. The mode is passed straight through
to ``RagService``, which turns it into a retrieval filter:

* ``knowledge`` — all of the user's ready documents,
* ``document``  — one document (``document_ids=[id]``),
* ``subject``   — every document of a subject,
* ``selected``  — an explicit list of documents,
* ``general``   — no retrieval; the response is explicitly labelled as
  ``based_on_documents=false`` so the UI can never confuse the two.
"""

from __future__ import annotations

from flask import Blueprint, request

from db.study_repositories import ChatRepository
from models.study import CHAT_MODES
from services.rag_service import RagService
from utils.auth_middleware import current_user_id, json_body, require_auth
from utils.errors import NotFoundError, ValidationError
from utils.responses import created, ok

bp = Blueprint("chat", __name__, url_prefix="/api/chat")


@bp.post("/ask")
@require_auth
def ask():
    """
    Ask a question.

    Body: ``{"question": "...", "mode": "knowledge", "document_ids": [],
    "subject": "", "session_id": null, "top_k": 6}``
    """
    payload = json_body()
    question = str(payload.get("question", "")).strip()
    if not question:
        raise ValidationError("Please type a question.", code="empty_question")

    mode = str(payload.get("mode", "knowledge")).lower()
    if mode not in CHAT_MODES:
        raise ValidationError(
            f"Unknown chat mode '{mode}'.",
            hint=f"Supported modes: {', '.join(CHAT_MODES)}.",
        )

    document_ids = payload.get("document_ids") or []
    if mode == "document" and not document_ids:
        raise ValidationError(
            "Chat With Document needs a document id.",
            code="missing_document",
        )
    if mode == "selected" and not document_ids:
        raise ValidationError(
            "Select at least one document for Selected Documents mode.",
            code="missing_documents",
        )
    if mode == "subject" and not payload.get("subject"):
        raise ValidationError(
            "Chat With Subject needs a subject.",
            code="missing_subject",
        )

    answer = RagService().ask(
        current_user_id(),
        question,
        mode=mode,
        document_ids=document_ids or None,
        subject=payload.get("subject") or None,
        session_id=payload.get("session_id") or None,
        top_k=int(payload.get("top_k") or 0) or None,
    )
    return created(answer.to_dict(), meta={"model": answer.model, "mode": mode})


@bp.get("/modes")
def modes():
    """The chat modes the API supports (so the UI can render them from the API)."""
    return ok(
        [
            {"id": "knowledge", "label": "Ask My Knowledge",
             "description": "Search every processed document."},
            {"id": "document", "label": "Chat With Document",
             "description": "Restrict answers to one document."},
            {"id": "subject", "label": "Chat With Subject",
             "description": "Restrict answers to one subject/category."},
            {"id": "selected", "label": "Selected Documents",
             "description": "Restrict answers to the documents you pick."},
            {"id": "general", "label": "General AI",
             "description": "No document retrieval — answered from the model alone."},
        ]
    )


@bp.get("/sessions")
@require_auth
def sessions():
    """Recent conversations with their titles and modes."""
    rows = ChatRepository().list_sessions(current_user_id(), limit=50)
    return ok(
        [
            {
                "id": str(row["_id"]),
                "title": row.get("title", ""),
                "mode": row.get("mode", "knowledge"),
                "message_count": row.get("message_count", 0),
                "updated_at": row.get("updated_at"),
            }
            for row in rows
        ]
    )


@bp.get("/sessions/<session_id>")
@require_auth
def session_detail(session_id: str):
    """Full transcript of one conversation (oldest message first)."""
    repository = ChatRepository()
    session = repository.get_session(session_id, current_user_id())
    if not session:
        raise NotFoundError("Chat session not found.", code="session_not_found")
    messages = repository.list_messages(session["_id"], limit=int(request.args.get("limit", 200)))
    return ok(
        {
            "id": str(session["_id"]),
            "title": session.get("title", ""),
            "mode": session.get("mode", "knowledge"),
            "messages": [
                {
                    "role": row.get("role"),
                    "content": row.get("content", ""),
                    "mode": row.get("mode", "knowledge"),
                    "sources": row.get("sources", []),
                    "created_at": row.get("created_at"),
                }
                for row in messages
            ],
        }
    )


@bp.delete("/sessions/<session_id>")
@require_auth
def delete_session(session_id: str):
    deleted = ChatRepository().delete_session(session_id, current_user_id())
    if not deleted:
        raise NotFoundError("Chat session not found.", code="session_not_found")
    return ok({"deleted": True})