"""
Research paper mode routes (``/api/research``) — brief §14.

Fields that cannot be found are returned as ``"Not found in document"`` with
``found: false``; the UI shows exactly that instead of a guess.
"""

from __future__ import annotations

from flask import Blueprint, request

from services.research_service import ResearchService
from utils.auth_middleware import current_user_id, json_body, require_auth
from utils.errors import ValidationError
from utils.responses import ok

bp = Blueprint("research", __name__, url_prefix="/api/research")

#: The buttons from brief §14.
ACTIONS = ("summarize", "methodology", "limitations", "study_notes")


@bp.get("/actions")
def actions():
    """Available research-paper actions (so the UI can render them from the API)."""
    return ok(
        [
            {"id": "summarize", "label": "Summarize"},
            {"id": "methodology", "label": "Explain Methodology"},
            {"id": "limitations", "label": "Find Limitations"},
            {"id": "study_notes", "label": "Generate Study Notes"},
        ]
    )


@bp.get("/<document_id>")
@require_auth
def extract(document_id: str):
    """
    Extract the paper structure.

    ``?use_llm=false`` returns the heuristic-only result (useful when Ollama is
    not running, and it makes the two layers easy to demonstrate in a viva).
    """
    use_llm = request.args.get("use_llm", "true").lower() not in ("0", "false", "no")
    return ok(ResearchService().extract(current_user_id(), document_id, use_llm=use_llm))


@bp.post("/<document_id>/action")
@require_auth
def run_action(document_id: str):
    """Run one action: ``{"action": "summarize"}``."""
    payload = json_body()
    action = str(payload.get("action", "")).strip().lower()
    if not action:
        raise ValidationError(
            "Provide an action.", code="missing_action", hint=f"Supported: {', '.join(ACTIONS)}."
        )
    return ok(ResearchService().action(current_user_id(), document_id, action))


@bp.post("/compare")
@require_auth
def compare_papers():
    """Compare two or more papers (delegates to the comparison service)."""
    payload = json_body()
    document_ids = payload.get("document_ids") or []
    if isinstance(document_ids, str):
        document_ids = [item.strip() for item in document_ids.split(",") if item.strip()]
    if len(document_ids) < 2:
        raise ValidationError("Select at least two papers to compare.", code="not_enough_documents")
    return ok(ResearchService().compare_papers(current_user_id(), document_ids))