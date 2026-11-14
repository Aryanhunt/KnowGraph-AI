"""
Response envelope helpers.

All endpoints answer with the same shape so the frontend ``api`` layer can treat
results uniformly::

    {"data": <payload>, "meta": {...}}      on success
    {"error": {"code": ..., "message": ...}} on failure (see utils.errors)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from flask import jsonify
from werkzeug.wrappers import Response

from utils.json_utils import to_jsonable


def ok(data: Any = None, *, meta: Optional[Dict[str, Any]] = None, status: int = 200) -> Tuple[Response, int]:
    body: Dict[str, Any] = {"data": to_jsonable(data)}
    if meta is not None:
        body["meta"] = to_jsonable(meta)
    return jsonify(body), status


def created(data: Any = None, *, meta: Optional[Dict[str, Any]] = None) -> Tuple[Response, int]:
    return ok(data, meta=meta, status=201)


def paginated(
    items: List[Any],
    *,
    total: int,
    page: int,
    page_size: int,
    extra: Optional[Dict[str, Any]] = None,
) -> Tuple[Response, int]:
    """Standard list envelope: items plus pagination metadata."""
    meta: Dict[str, Any] = {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if page_size else 0,
        "has_more": page * page_size < total,
    }
    if extra:
        meta.update(to_jsonable(extra))
    return ok(items, meta=meta)