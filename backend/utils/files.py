"""
File validation and storage helpers.

Uploaded binaries are *never* stored inside MongoDB (brief §5). They are written
to ``backend/storage/uploads/<user_id>/`` with a UUID-prefixed, sanitised name,
and only the resulting path plus metadata is persisted.
"""

from __future__ import annotations

import hashlib
import mimetypes
import uuid
from dataclasses import dataclass
from pathlib import Path

from utils.errors import PayloadTooLargeError, UnsupportedFileTypeError, ValidationError
from utils.security import sanitize_filename

# Extension → (category, accepted MIME types). MIME types are used as a second
# signal, but the extension decides which extractor runs.
SUPPORTED_TYPES = {
    "pdf": ("pdf", {"application/pdf", "application/x-pdf", "application/octet-stream"}),
    "png": ("image", {"image/png"}),
    "jpg": ("image", {"image/jpeg"}),
    "jpeg": ("image", {"image/jpeg"}),
    "webp": ("image", {"image/webp"}),
    "tif": ("image", {"image/tiff"}),
    "tiff": ("image", {"image/tiff"}),
    "bmp": ("image", {"image/bmp", "image/x-ms-bmp"}),
    "docx": ("docx", {"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                      "application/zip", "application/octet-stream"}),
    "txt": ("text", {"text/plain", "application/octet-stream"}),
    "md": ("text", {"text/markdown", "text/x-markdown", "text/plain", "application/octet-stream"}),
}

# Human readable list for error messages and the UI.
SUPPORTED_EXTENSIONS = tuple(sorted(SUPPORTED_TYPES))


@dataclass(frozen=True)
class UploadInfo:
    """Result of validating an incoming upload."""

    original_filename: str
    safe_filename: str
    extension: str
    category: str          # pdf | image | docx | text
    declared_mime: str
    size_bytes: int
    stored_path: Path


def get_extension(filename: str) -> str:
    return Path(filename or "").suffix.lower().lstrip(".")


def category_for_extension(extension: str) -> str:
    entry = SUPPORTED_TYPES.get(extension.lower())
    return entry[0] if entry else ""


def build_stored_path(upload_dir: Path, user_id: str, original_filename: str) -> Path:
    """``<upload_dir>/<user_id>/<uuid>-<safe_name>`` — collision free per upload."""
    safe_name = sanitize_filename(original_filename)
    user_dir = Path(upload_dir) / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir / f"{uuid.uuid4().hex[:12]}-{safe_name}"


def validate_upload(
    *,
    original_filename: str,
    size_bytes: int,
    declared_mime: str,
    upload_dir: Path,
    user_id: str,
    max_upload_mb: int,
) -> UploadInfo:
    """
    Validate an upload request and compute its destination path.

    Raises :class:`UnsupportedFileTypeError`, :class:`PayloadTooLargeError` or
    :class:`ValidationError` with a message the UI can display directly.
    """
    if not original_filename:
        raise ValidationError("A file must be provided.")

    extension = get_extension(original_filename)
    if not extension:
        raise UnsupportedFileTypeError(
            "The file has no extension, so its type cannot be verified.",
            hint=f"Supported types: {', '.join(SUPPORTED_EXTENSIONS)}",
        )
    if extension not in SUPPORTED_TYPES:
        raise UnsupportedFileTypeError(
            f".{extension} files are not supported.",
            hint=f"Supported types: {', '.join(SUPPORTED_EXTENSIONS)}",
        )

    if size_bytes <= 0:
        raise ValidationError("The uploaded file is empty.")
    max_bytes = max_upload_mb * 1024 * 1024
    if size_bytes > max_bytes:
        raise PayloadTooLargeError(
            f"The file is larger than the {max_upload_mb} MB limit.",
            hint="Increase MAX_UPLOAD_MB in backend/.env or upload a smaller file.",
            details={"size_bytes": size_bytes, "max_bytes": max_bytes},
        )

    category = category_for_extension(extension)
    stored_path = build_stored_path(upload_dir, user_id, original_filename)
    return UploadInfo(
        original_filename=original_filename,
        safe_filename=sanitize_filename(original_filename),
        extension=extension,
        category=category,
        declared_mime=declared_mime or "application/octet-stream",
        size_bytes=size_bytes,
        stored_path=stored_path,
    )


def detect_mime_type(path: Path, fallback: str = "application/octet-stream") -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or fallback


def sha256_of_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Checksum used to detect duplicate uploads without reading files twice."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def human_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"