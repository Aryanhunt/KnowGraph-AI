"""
Knowledge graph routes (``/api/graph``).

Serves the structured graph produced by the pipeline (brief §9) and the
personalised learning path derived from it (brief §12).
"""

from __future__ import annotations

from flask import Blueprint, request

from db.study_repositories import ConceptRepository, RelationRepository
from models.graph import RELATION_TYPES
from services.graph_service import GraphService
from utils.auth_middleware import current_user_id, require_auth
from utils.responses import ok

from utils.logging_setup import get_logger

logger = get_logger(__name__)

bp = Blueprint("graph", __name__, url_prefix="/api/graph")


def _document_ids() -> list:
    """Accept ``?document_ids=a,b`` or repeated ``?document_ids=a&document_ids=b``."""
    raw = request.args.getlist("document_ids")
    if len(raw) == 1 and "," in raw[0]:
        raw = [item.strip() for item in raw[0].split(",") if item.strip()]
    return [item for item in raw if item]


@bp.get("")
@require_auth
def graph():
    """
    Nodes and edges for the interactive graph visualisation.

    Edge filtering (Phase: graph accuracy):
      * ``verification=verified`` (default) — only text-supported edges,
      * ``verification=inferred`` — verified + model-derived,
      * ``verification=all`` — everything stored (weak associations included),
      * ``min_confidence=0.5`` — explicit floor that overrides the default band.
    """
    min_confidence = request.args.get("min_confidence")
    try:
        min_confidence_value = float(min_confidence) if min_confidence is not None else None
    except (TypeError, ValueError):
        from utils.errors import ValidationError

        raise ValidationError(
            "min_confidence must be a number between 0 and 1.",
            code="invalid_min_confidence",
        )
    if min_confidence_value is not None and not 0 <= min_confidence_value <= 1:
        from utils.errors import ValidationError

        raise ValidationError(
            "min_confidence must be between 0 and 1.",
            code="invalid_min_confidence",
        )

    verification = (request.args.get("verification") or "verified").strip().lower()
    if verification in ("inferred", "all_plus_inferred"):
        # "verified + inferred" is expressed as an "all" scan with a floor.
        verification = "all"
        if min_confidence_value is None:
            min_confidence_value = 0.5
    if verification not in ("verified", "all"):
        from utils.errors import ValidationError

        raise ValidationError(
            f"Unknown verification filter '{verification}'.",
            code="invalid_verification",
            hint="Supported values: verified, inferred, all.",
        )

    return ok(
        GraphService().get_graph(
            current_user_id(),
            document_ids=_document_ids() or None,
            search=request.args.get("search") or None,
            limit=int(request.args.get("limit", 80)),
            verification=verification,
            min_confidence=min_confidence_value,
        )
    )


@bp.get("/status")
@require_auth
def status():
    """Concept/relation counts, used by the graph page's empty state."""
    user_id = current_user_id()
    concepts = ConceptRepository().count(user_id)
    relations_repo = RelationRepository()
    return ok(
        {
            "concept_count": concepts,
            "relation_count": relations_repo.count(user_id),
            "relation_types": list(RELATION_TYPES),
            "verified_relation_count": relations_repo.count_by_verification(user_id, "verified"),
            "inferred_relation_count": relations_repo.count_by_verification(user_id, "inferred"),
            "uncertain_relation_count": relations_repo.count_by_verification(user_id, "uncertain"),
            "message": (
                "Upload a document to build the graph."
                if concepts == 0
                else "Click a concept to see its sources and related concepts."
            ),
        }
    )


@bp.get("/concepts")
@require_auth
def concepts():
    """Concept list with importance scores (used by the sidebar and search)."""
    rows = ConceptRepository().list_for_user(
        current_user_id(),
        search=request.args.get("search") or None,
        document_ids=_document_ids() or None,
        limit=int(request.args.get("limit", 100)),
    )
    return ok(
        [
            {
                "slug": row.get("slug"),
                "label": row.get("label", ""),
                "score": row.get("score", 0.0),
                "occurrences": row.get("occurrences", 0),
                "document_count": row.get("document_count", 0),
                "definition": row.get("definition", ""),
            }
            for row in rows
        ]
    )


@bp.get("/concepts/<slug>")
@require_auth
def concept_detail(slug: str):
    """
    Everything the concept panel shows: definition, related concepts and the
    documents/pages the concept was found in (brief §9).
    """
    return ok(GraphService().concept_detail(current_user_id(), slug))


@bp.get("/learning-path")
@require_auth
def learning_path():
    """Prerequisite revision plan for a target concept (brief §12)."""
    target = request.args.get("target", "").strip()
    explain = request.args.get("explain", "true").lower() not in ("0", "false", "no")
    from utils.errors import ValidationError

    if not target:
        raise ValidationError("Provide a target concept using ?target=", code="missing_target")
    return ok(GraphService().learning_path(current_user_id(), target, explain_with_llm=explain))


@bp.get("/relations")
@require_auth
def relations():
    """Raw relations, optionally filtered by type (``?relation=requires``)."""
    relation = request.args.get("relation") or None
    if relation and relation not in RELATION_TYPES:
        from utils.errors import ValidationError

        raise ValidationError(
            f"Unknown relation type '{relation}'.",
            hint=f"Supported types: {', '.join(RELATION_TYPES)}.",
        )
    rows = RelationRepository().list_for_user(
        current_user_id(), relation=relation, limit=int(request.args.get("limit", 100))
    )
    return ok(
        [
            {
                "source_slug": row.get("source_slug"),
                "target_slug": row.get("target_slug"),
                "relation": row.get("relation"),
                "method": row.get("method"),
                "weight": row.get("weight"),
                "confidence": row.get("confidence"),
                "verification_status": row.get("verification_status"),
                "evidence_count": row.get("evidence_count"),
                "evidence": row.get("evidence", []),
            }
            for row in rows
        ]
    )


@bp.get("/relations/evidence")
@require_auth
def relation_evidence():
    """
    Full evidence for one edge — the edge-inspector payload.

    ``/api/graph/relations/evidence?source=…&target=…&relation=requires``
    """
    from utils.errors import ValidationError

    source = request.args.get("source", "").strip()
    target = request.args.get("target", "").strip()
    relation = request.args.get("relation", "").strip()
    if not source or not target or not relation:
        raise ValidationError(
            "Provide source, target and relation.",
            code="missing_relation_args",
        )
    return ok(GraphService().edge_evidence(current_user_id(), source, target, relation))


@bp.post("/relations/verify")
@require_auth
def verify_relation():
    """Accept or reject an edge (rejected edges are hidden, never deleted)."""
    body = request.get_json(silent=True) or {}
    from utils.errors import ValidationError

    source = str(body.get("source", "")).strip()
    target = str(body.get("target", "")).strip()
    relation = str(body.get("relation", "")).strip()
    status = str(body.get("status", "")).strip()
    if not source or not target or not relation:
        raise ValidationError(
            "Provide source, target and relation.",
            code="missing_relation_args",
        )
    if not status:
        raise ValidationError("Provide a status.", code="missing_status")
    return ok(GraphService().set_edge_verification(current_user_id(), source, target, relation, status))


@bp.post("/upload-relations")
@require_auth
def upload_relations():
    """Upload a relationship file (PDF/TXT/JSON/JSONL/CSV) to add edges to the graph.

    The file is parsed and every edge whose source and target match existing
    concepts is stored with ``method="user_specified"``, ``verification_status="verified"``
    and confidence 0.90. Edges referencing unknown concepts are reported but not
    stored, so you can fix the labels.
    """
    from services.relationship_parser import RelationshipParser

    file_storage = next(
        (
            request.files.get(name)
            for name in ("file", "relationships", "relationships_file")
            if request.files.get(name) is not None
        ),
        None,
    )
    if file_storage is None:
        raise ValidationError(
            "No file uploaded.",
            code="missing_file",
            hint="Send a file in a form field named 'file' (PDF/TXT/JSON/JSONL/CSV).",
        )

    filename = getattr(file_storage, "filename", "") or ""
    if not filename:
        raise ValidationError("No filename.", code="missing_filename")

    data = file_storage.read()
    if not data:
        file_storage.stream.seek(0)
        data = file_storage.stream.read()
    if not data:
        raise ValidationError("Empty file.", code="empty_file")

    user_id = current_user_id()
    parser = RelationshipParser(ConceptRepository())
    result = parser.parse_bytes(filename, data, user_id)

    # Persist every resolved edge with high confidence.
    stored = 0
    for edge in result.get("matched", []):
        try:
            RelationRepository().upsert(
                user_id=user_id,
                source_slug=edge["source_slug"],
                target_slug=edge["target_slug"],
                relation=edge.get("relation", "related_to"),
                method="user_specified",
                weight=2.0,
                evidence={
                    "snippet": edge.get("why", "") or f"{edge['source']} → {edge['target']}",
                    "document_title": edge.get("chapter", ""),
                    "page_number": edge.get("page"),
                },
                confidence=0.90,
                verification_status="verified",
            )
            stored += 1
        except Exception as exc:
            logger.warning(
                "Failed to store edge %s→%s: %s",
                edge.get("source_slug"),
                edge.get("target_slug"),
                exc,
            )

    return ok(
        {
            "rows_parsed": result.get("rows_total", 0),
            "edges_resolved": result.get("edges_resolved", 0),
            "edges_unresolved": result.get("edges_unresolved", 0),
            "edges_stored": stored,
            "unmatched_sources": result.get("unmatched_sources", {}),
            "unmatched_targets": result.get("unmatched_targets", {}),
        }
    )


