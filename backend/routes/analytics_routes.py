"""
Analytics routes (``/api/analytics``).

Exposes the dashboard counters, the knowledge-gap list and the per-subject
progress view. All values come from recorded activity (brief §11).
"""

from __future__ import annotations

from flask import Blueprint

from services.analytics_service import AnalyticsService
from utils.auth_middleware import current_user_id, require_auth
from utils.responses import ok

bp = Blueprint("analytics", __name__, url_prefix="/api/analytics")


@bp.get("/dashboard")
@require_auth
def dashboard():
    """Document counts, study totals, recent activity."""
    return ok(AnalyticsService().dashboard(current_user_id()))


@bp.get("/knowledge-gaps")
@require_auth
def knowledge_gaps():
    """
    Weak / stale topics with plain-language status labels and the legend that
    explains exactly how each label is derived.
    """
    return ok(AnalyticsService().knowledge_gaps(current_user_id()))


@bp.get("/progress")
@require_auth
def progress():
    """Progress grouped by subject for the progress dashboard."""
    return ok(AnalyticsService().progress(current_user_id()))


@bp.get("/topics")
@require_auth
def topics():
    """Flat topic status list (used by the analytics table)."""
    service = AnalyticsService()
    return ok(service.topic_status(current_user_id()))