"""
Authentication routes (``/api/auth``).

Thin HTTP layer only: validation and business rules live in ``AuthService``.
"""

from __future__ import annotations

from flask import Blueprint

from services.auth_service import AuthService
from utils.auth_middleware import current_user_id, json_body, require_auth
from utils.responses import created, ok

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.post("/register")
def register():
    """Create an account and return the first access token."""
    payload = json_body()
    service = AuthService()
    result = service.register(
        email=str(payload.get("email", "")),
        full_name=str(payload.get("full_name", "")),
        password=str(payload.get("password", "")),
    )
    return created(result)


@bp.post("/login")
def login():
    """Exchange email + password for an access token."""
    payload = json_body()
    result = AuthService().login(
        email=str(payload.get("email", "")),
        password=str(payload.get("password", "")),
    )
    return ok(result)


@bp.get("/me")
@require_auth
def me():
    """The signed-in user's profile."""
    return ok(AuthService().get_profile(current_user_id()))


@bp.post("/change-password")
@require_auth
def change_password():
    payload = json_body()
    AuthService().change_password(
        current_user_id(),
        current_password=str(payload.get("current_password", "")),
        new_password=str(payload.get("new_password", "")),
    )
    return ok({"changed": True})