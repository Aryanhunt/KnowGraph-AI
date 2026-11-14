"""
Authentication middleware (brief §21).

``require_auth`` is the single guard every protected route uses. It:

1. reads the ``Authorization: Bearer <token>`` header,
2. verifies the JWT signature/expiry with the configured secret,
3. loads the user record (so a deleted account cannot keep using a valid token),
4. stores the id on ``flask.g`` for the route to scope its queries with.

Because repositories filter every query by ``user_id``, this decorator is what
makes per-user isolation actually hold.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Optional

from flask import g, request

from config.settings import get_settings
from db.repositories import UserRepository
from utils.errors import AuthError
from utils.logging_setup import get_logger
from utils.security import decode_access_token

logger = get_logger(__name__)


def _token_from_request() -> Optional[str]:
    """Extract a bearer token from the header (or a ``token`` query parameter)."""
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    if header and "." in header:            # tolerate a bare token
        return header.strip()
    return request.args.get("token")


def resolve_user(token: str) -> dict:
    """Verify a token and return its user document, or raise :class:`AuthError`."""
    settings = get_settings()
    payload = decode_access_token(token, secret=settings.secret_key)
    user_id = payload.get("sub")
    if not user_id:
        raise AuthError("The session token is missing its subject.", code="invalid_token")

    user = UserRepository().find_by_id(user_id)
    if not user:
        raise AuthError(
            "Your account no longer exists.",
            code="user_not_found",
            hint="Please register again.",
        )
    return user


def require_auth(view: Callable) -> Callable:
    """Decorator for routes that need a signed-in user."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        token = _token_from_request()
        if not token:
            raise AuthError(
                "Please log in to continue.",
                hint="Send an Authorization: Bearer <token> header.",
            )
        user = resolve_user(token)
        g.user = user
        g.user_id = str(user["_id"])
        return view(*args, **kwargs)

    return wrapper


def current_user_id() -> str:
    """The authenticated user's id (raises when used outside a guarded route)."""
    user_id = getattr(g, "user_id", None)
    if not user_id:
        raise AuthError("Please log in to continue.")
    return user_id


def current_user() -> dict:
    user = getattr(g, "user", None)
    if not user:
        raise AuthError("Please log in to continue.")
    return user


def optional_user() -> Optional[dict]:
    """Best-effort user lookup, used by endpoints that work signed-in or not."""
    token = _token_from_request()
    if not token:
        return None
    try:
        return resolve_user(token)
    except Exception:  # noqa: BLE001 - an invalid token simply means "anonymous"
        return None


def pagination_args() -> dict:
    """Read ``page``/``page_size`` from the query string with safe defaults."""
    def _int(name: str, default: int, maximum: int) -> int:
        try:
            return max(1, min(maximum, int(request.args.get(name, default))))
        except (TypeError, ValueError):
            return default

    return {"page": _int("page", 1, 10_000), "page_size": _int("page_size", 20, 100)}


def json_body() -> dict:
    """Return the JSON body as a dict, tolerating empty/invalid payloads."""
    payload: Any = request.get_json(silent=True)
    if isinstance(payload, dict):
        return payload
    return {}