"""
Security helpers: password hashing, JWT access tokens, filename sanitisation and
path-traversal protection (brief §21).

* passwords are hashed with bcrypt (never stored in plain text),
* sessions are proven with a signed JWT access token,
* uploaded filenames are sanitised before touching the filesystem,
* every file path is resolved *inside* the storage root, so one user can never
  read or delete another user's files.
"""

from __future__ import annotations

import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import bcrypt
import jwt

from utils.errors import AuthError, ConfigurationError, ValidationError

BCRYPT_ROUNDS = 12
MIN_PASSWORD_LENGTH = 8
JWT_ALGORITHM = "HS256"

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._ -]+")
_MULTI_SEPARATOR = re.compile(r"[_\-\s]{2,}")

#: Weak passwords refused outright.
COMMON_PASSWORDS = {
    "password", "password1", "12345678", "123456789", "qwerty123",
    "letmein123", "admin1234", "iloveyou", "abcd1234",
}


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """Return a bcrypt hash for ``password``."""
    if not password:
        raise ValidationError("A password is required.")
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """bcrypt verification; returns False for malformed hashes instead of raising."""
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def validate_password_strength(password: str) -> None:
    """Enforce a small, explainable password policy at registration time."""
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
        )
    if password.lower() in COMMON_PASSWORDS:
        raise ValidationError("That password is too common. Please choose another one.")
    if password.isdigit():
        raise ValidationError("Password must contain more than digits.")


# ---------------------------------------------------------------------------
# JWT access tokens
# ---------------------------------------------------------------------------
def get_secret_key() -> str:
    """Read the signing secret, refusing the shipped placeholder value."""
    from config.settings import get_settings

    secret = get_settings().secret_key
    if not secret or secret.startswith("change-me"):
        raise ConfigurationError(
            "SECRET_KEY is not set.",
            hint="Copy backend/.env.example to backend/.env and set a long random SECRET_KEY.",
        )
    return secret


def create_access_token(
    subject: str,
    *,
    secret: Optional[str] = None,
    expires_in_hours: int = 12,
    extra_claims: Optional[Dict[str, Any]] = None,
) -> str:
    """Sign a JWT for ``subject`` (the user id)."""
    signing_key = secret or get_secret_key()
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=expires_in_hours)).timestamp()),
        "jti": secrets.token_hex(8),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, signing_key, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, *, secret: Optional[str] = None) -> Dict[str, Any]:
    """Decode a token or raise a friendly :class:`AuthError`."""
    signing_key = secret or get_secret_key()
    try:
        return jwt.decode(token, signing_key, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError(
            "Your session has expired.", code="token_expired", hint="Please log in again."
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError(
            "The session token is invalid.", code="invalid_token", hint="Please log in again."
        ) from exc


def sanitize_filename(filename: str, *, max_length: int = 120) -> str:
    """
    Produce a safe filename.

    Unicode is normalised, directory components and control characters are
    removed, spaces collapse to underscores, and the length is capped while
    preserving the extension.
    """
    raw = unicodedata.normalize("NFKC", filename or "").strip()
    raw = raw.replace("\\", "/").split("/")[-1]      # drop any directory part
    raw = raw.replace("\x00", "")

    stem, dot, extension = raw.rpartition(".")
    if not dot:                                      # no extension present
        stem, extension = raw, ""

    stem = _UNSAFE_FILENAME_CHARS.sub("_", stem)
    stem = _MULTI_SEPARATOR.sub("_", stem).strip("._- ")
    extension = _UNSAFE_FILENAME_CHARS.sub("", extension.lower())
    stem = (stem or "document")[:max_length]
    return f"{stem}.{extension}" if extension else stem


def safe_resolve(base_dir: Path, *parts: str) -> Path:
    """
    Join ``parts`` onto ``base_dir`` and refuse anything that escapes it.

    Single choke point that stops ``../../etc/passwd`` style paths coming from a
    filename or a JSON payload.
    """
    base = Path(base_dir).resolve()
    candidate = base.joinpath(*parts).resolve()
    if candidate != base and not str(candidate).startswith(str(base) + "/"):
        raise ValidationError(
            "The resolved path is outside the storage directory.",
            code="unsafe_path",
        )
    return candidate


def safe_remove(path, *, allowed_root: Path) -> bool:
    """
    Delete a file only when it lives under ``allowed_root``.

    Returns True when a file was removed, False when it was missing or outside the
    allowed root. Never raises: a failed cleanup must not break a request.
    """
    if not path:
        return False
    try:
        resolved = safe_resolve(Path(allowed_root), str(path))
    except (ValidationError, OSError, ValueError):
        return False
    try:
        if resolved.is_file():
            resolved.unlink()
            return True
    except OSError:
        return False
    return False