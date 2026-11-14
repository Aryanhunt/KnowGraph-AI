"""
JSON serialisation helpers.

MongoDB documents contain ``ObjectId`` and ``datetime`` values, NumPy returns
``float32``/``int64`` scalars, and some services work with ``Path`` objects. The
API must always answer with valid JSON, so everything funnels through
:func:`to_jsonable`. ``app.py`` registers :class:`KnowGraphJSONProvider` so even
a route that forgets to convert values still returns valid JSON.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

try:  # bson ships with pymongo, which is a hard requirement
    from bson import ObjectId
except ImportError:  # pragma: no cover - pymongo missing
    ObjectId = None  # type: ignore[assignment]


def to_jsonable(value: Any) -> Any:
    """Recursively convert MongoDB / NumPy / Path values into JSON-safe types."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        # NumPy floats behave like floats but are not JSON serialisable.
        return float(value)
    if isinstance(value, (datetime, date)):
        # Persist timezone-aware UTC ISO strings so the frontend can format them.
        if isinstance(value, date) and not isinstance(value, datetime):
            return value.isoformat()
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    if ObjectId is not None and isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]

    # NumPy scalars / arrays expose .item() or .tolist().
    if hasattr(value, "item") and callable(getattr(value, "item")):
        try:
            return to_jsonable(value.item())
        except (ValueError, TypeError):  # pragma: no cover - non scalar array
            pass
    if hasattr(value, "tolist") and callable(getattr(value, "tolist")):
        return to_jsonable(value.tolist())

    return str(value)


def project_many(documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Shorthand used a lot in routes to serialise cursor results."""
    return [to_jsonable(document) for document in documents]


def install_json_provider(app) -> None:
    """Teach Flask to serialise BSON/NumPy values automatically."""
    from flask.json.provider import DefaultJSONProvider

    class KnowGraphJSONProvider(DefaultJSONProvider):
        @staticmethod
        def default(value: Any) -> Any:  # noqa: D102 - inherited contract
            return to_jsonable(value)

    app.json = KnowGraphJSONProvider(app)