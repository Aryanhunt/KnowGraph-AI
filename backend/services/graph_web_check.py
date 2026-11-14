"""
Optional web cross-check for relation verification.

Disabled by default (GRAPH_ENABLE_WEB_CHECK=false). Uses only plain HTTP page
retrieval — no search API, no key, no external AI. Web results are NEVER the
basis for creating a relation: ``check_relation`` returns advisory hints only,
and callers must not store/upsert anything from its output.
"""

from __future__ import annotations

import html
import logging
import re
from typing import Dict, Optional

from config.settings import Settings, get_settings
from utils.text import normalize_for_match

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 6


def relation_web_hint(
    source: str,
    target: str,
    relation: str,
    *,
    settings: Optional[Settings] = None,
) -> Optional[Dict[str, object]]:
    """
    Optional advisory lookup: fetch the source concept's encyclopedia page and
    check whether the target concept is named on it.

    Returns ``{"source": "wikipedia", "mentions_target": bool}`` or ``None``
    when disabled/unavailable. Never reason enough to create an edge.
    """
    current = settings or get_settings()
    if not getattr(current, "graph_enable_web_check", False):
        return None
    timeout = max(2, int(getattr(current, "graph_web_check_timeout_seconds", 6) or 6))
    slug = normalize_for_match(source or "").replace(" ", "_")
    if not slug:
        return None
    try:
        import urllib.request

        url = f"https://en.wikipedia.org/wiki/{slug}"
        request = urllib.request.Request(url, headers={"User-Agent": "KnowGraphAI/1.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(400_000).decode("utf-8", errors="ignore")
    except Exception as exc:  # noqa: BLE001 - advisory only
        logger.debug("Web relation check skipped for %s: %s", source, exc)
        return None
    body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.DOTALL)
    text = html.unescape(re.sub(r"<[^>]+>", " ", body))
    mentions = normalize_for_match(target or "") in normalize_for_match(text)
    return {"source": "wikipedia", "mentions_target": bool(mentions)}
