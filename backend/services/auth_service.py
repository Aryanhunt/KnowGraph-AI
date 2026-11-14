"""
Authentication service (brief §21).

Responsibilities:
* register a user (unique email, bcrypt-hashed password),
* log a user in and issue a JWT access token,
* expose the public profile shape used by the API.

The token subject is the MongoDB id, and every document/graph/study query is
scoped by that id, which is how one user is prevented from touching another
user's data.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from config.settings import Settings, get_settings
from db.repositories import UserRepository
from utils.errors import AuthError, ConflictError, NotFoundError, ValidationError
from utils.logging_setup import get_logger
from utils.security import (
    create_access_token,
    hash_password,
    validate_password_strength,
    verify_password,
)
from utils.text import normalize_for_match

logger = get_logger(__name__)

EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"


class AuthService:
    """Encapsulates registration, login and profile lookups."""

    def __init__(self, settings: Optional[Settings] = None, users: Optional[UserRepository] = None) -> None:
        self.settings = settings or get_settings()
        self.users = users or UserRepository()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    @staticmethod
    def public_profile(user: Dict[str, Any]) -> Dict[str, Any]:
        """Strip the password hash before a user object leaves the service."""
        return {
            "id": str(user.get("_id")),
            "email": user.get("email_display") or user.get("email", ""),
            "full_name": user.get("full_name", ""),
            "created_at": user.get("created_at"),
            "last_login_at": user.get("last_login_at"),
        }

    def register(self, *, email: str, full_name: str, password: str) -> Dict[str, Any]:
        """Create an account and return ``{"user": ..., "token": ...}``."""
        email = (email or "").strip()
        full_name = (full_name or "").strip()

        import re

        if not re.match(EMAIL_RE, email):
            raise ValidationError("Please enter a valid email address.")
        if len(full_name) < 2:
            raise ValidationError("Please enter your name.")
        validate_password_strength(password)

        if self.users.find_by_email(email):
            raise ConflictError(
                "An account with this email already exists.",
                code="email_taken",
                hint="Try logging in instead.",
            )

        user_id = self.users.create(
            email=email, full_name=full_name, password_hash=hash_password(password)
        )
        user = self.users.find_by_id(user_id)
        assert user is not None
        logger.info("Registered user %s", normalize_for_match(email))
        return {"user": self.public_profile(user), "token": self._issue_token(user)}

    def login(self, *, email: str, password: str) -> Dict[str, Any]:
        """Verify credentials and return ``{"user": ..., "token": ...}``."""
        user = self.users.find_by_email((email or "").strip())
        if not user or not verify_password(password or "", user.get("password_hash", "")):
            # One message for both cases so the response cannot be used to
            # discover which emails exist.
            raise AuthError(
                "Incorrect email or password.",
                code="invalid_credentials",
                hint="Check your details and try again.",
            )
        self.users.touch_login(user["_id"])
        refreshed = self.users.find_by_id(user["_id"]) or user
        logger.info("User %s logged in", normalize_for_match(email))
        return {"user": self.public_profile(refreshed), "token": self._issue_token(refreshed)}

    def get_profile(self, user_id: Any) -> Dict[str, Any]:
        user = self.users.find_by_id(user_id)
        if not user:
            raise NotFoundError("Your account could not be found.", code="user_not_found")
        return self.public_profile(user)

    def change_password(self, user_id: Any, *, current_password: str, new_password: str) -> None:
        user = self.users.find_by_id(user_id)
        if not user:
            raise NotFoundError("Your account could not be found.", code="user_not_found")
        if not verify_password(current_password or "", user.get("password_hash", "")):
            raise AuthError("The current password is incorrect.", code="invalid_credentials")
        validate_password_strength(new_password)
        self.users.collection.update_one(
            {"_id": user["_id"]}, {"$set": {"password_hash": hash_password(new_password)}}
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _issue_token(self, user: Dict[str, Any]) -> str:
        return create_access_token(
            str(user["_id"]),
            secret=self.settings.secret_key,
            expires_in_hours=self.settings.access_token_hours,
            extra_claims={"email": user.get("email", "")},
        )