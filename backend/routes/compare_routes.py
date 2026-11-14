"""
Document comparison route (``/api/compare``) — brief §13.

Returns the deterministic topic comparison plus, when the local model is
available, a narrative section (methodology / variations) whose items name the
documents they refer to.
"""

from __future__ import annotations

from flask import Blueprint

from services.compare_service import CompareService
from utils.auth_middleware import current_user_id, json_body, require_auth
from utils.errors import ValidationError
from utils.responses import ok

bp = Blueprint("compare", __name__, url_prefix="/api/compare")


@bp.post("")
@require_auth
def compare():
    """Compare two or more documents.

    Body: ``{"document_ids": ["<id>", "<id>", ...]}``
    """
    payload = json_body()
    document_ids = payload.get("document_ids") or []
    if isinstance(document_ids, str):
        document_ids = [item.strip() for item in document_ids.split(",") if item.strip()]
    if len(document_ids) < 2:
        raise ValidationError(
            "Select at least two documents to compare.",
            code="not_enough_documents",
        )
    return ok(CompareService().compare(current_user_id(), document_ids))