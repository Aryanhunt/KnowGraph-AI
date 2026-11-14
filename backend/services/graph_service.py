"""
Knowledge graph service (brief §9, §12).

Reads the concepts and typed relations produced by the pipeline and serves them
in the exact shape an interactive graph library needs:

* :meth:`get_graph`      → ``{"nodes": [...], "edges": [...], "stats": {...}}``
* :meth:`concept_detail` → one concept, its neighbours and its page sources
* :meth:`learning_path`  → prerequisite chain for a target concept (brief §12)

Every node and edge keeps its document/page evidence, so clicking a node in the
UI can show *where* the concept came from — nothing in the graph is invented.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from config.settings import Settings, get_settings
from db.study_repositories import ConceptRepository, RelationRepository
from models.graph import RELATION_PHRASES
from utils.errors import NotFoundError
from utils.logging_setup import get_logger
from utils.text import normalize_for_match

logger = get_logger(__name__)


class GraphService:
    """Read-side API for the stored knowledge graph."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        concepts: Optional[ConceptRepository] = None,
        relations: Optional[RelationRepository] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.concepts = concepts or ConceptRepository()
        self.relations = relations or RelationRepository()

    # ------------------------------------------------------------------
    # Full graph
    # ------------------------------------------------------------------
    def get_graph(
        self,
        user_id: Any,
        *,
        document_ids: Optional[List[Any]] = None,
        search: Optional[str] = None,
        limit: int = 80,
        verification: Optional[str] = None,
        min_confidence: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Nodes + edges for the interactive graph panel.

        The node list is capped (``limit``) by importance so the visualisation
        stays readable; edges are limited to those between the returned nodes.

        By default only ``verified`` edges above the verified floor are
        returned — weak co-occurrence stays in the database but is hidden
        unless the caller opts into ``all``.
        """
        from models.graph import RELATION_CONFIDENCE

        user_id = str(user_id)
        concepts = self.concepts.list_for_user(
            user_id,
            search=search,
            document_ids=document_ids,
            limit=max(10, limit),
        )
        slugs = [concept["slug"] for concept in concepts]
        slug_set = set(slugs)

        verification_query = (verification or "verified").strip().lower()
        include_all = verification_query == "all"
        # An explicit threshold always applies; otherwise "all" defaults to no
        # floor and "verified" defaults to the verified confidence band.
        min_conf = (
            float(min_confidence)
            if min_confidence is not None
            else (0.0 if include_all else float(RELATION_CONFIDENCE["verified_min"]))
        )
        relation_rows = self.relations.list_for_user(
            user_id,
            slugs=slugs,
            limit=limit * 6,
            verification=None if include_all else "verified",
            min_confidence=min_conf,
        )
        edges: List[Dict[str, Any]] = []
        for relation in relation_rows:
            if relation["source_slug"] not in slug_set or relation["target_slug"] not in slug_set:
                continue
            evidence = relation.get("evidence", []) or []
            edges.append(
                {
                    "id": str(relation.get("_id")),
                    "source": relation["source_slug"],
                    "target": relation["target_slug"],
                    "relation": relation.get("relation", "related_to"),
                    "label": RELATION_PHRASES.get(relation.get("relation", ""), "relates to"),
                    "method": relation.get("method", "cooccurrence"),
                    "weight": float(relation.get("weight", 1.0)),
                    "confidence": float(relation.get("confidence", 0.0) or 0.0),
                    "verification_status": relation.get("verification_status") or "uncertain",
                    "evidence_count": int(relation.get("evidence_count", len(evidence))),
                    "documents": [
                        {
                            "document_id": item.get("document_id"),
                            "title": item.get("document_title", ""),
                            "page_number": item.get("page_number"),
                        }
                        for item in evidence[:3]
                    ],
                }
            )

        nodes = [self._node(concept) for concept in concepts]
        return {
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "concept_count": self.concepts.count(user_id),
                "relation_count": self.relations.count(user_id),
                "shown_nodes": len(nodes),
                "shown_edges": len(edges),
            },
        }

    @staticmethod
    def _node(concept: Dict[str, Any]) -> Dict[str, Any]:
        page_refs = concept.get("page_refs", []) or []
        documents = []
        seen = set()
        for ref in page_refs:
            key = str(ref.get("document_id"))
            if key in seen:
                continue
            seen.add(key)
            documents.append(
                {
                    "document_id": key,
                    "title": ref.get("document_title", ""),
                    "pages": sorted(
                        {
                            int(r.get("page_number"))
                            for r in page_refs
                            if str(r.get("document_id")) == key and r.get("page_number")
                        }
                    )[:12],
                }
            )
        return {
            "id": concept["slug"],
            "label": concept.get("label", concept["slug"]),
            "score": float(concept.get("score", 0.0)),
            "occurrences": int(concept.get("occurrences", 0)),
            "document_count": int(concept.get("document_count", 0)),
            "definition": concept.get("definition", ""),
            "documents": documents,
        }

    def edge_evidence(
        self,
        user_id: Any,
        source_slug: str,
        target_slug: str,
        relation: str,
    ) -> Dict[str, Any]:
        """Full evidence for one stored edge (the edge-inspector payload)."""
        row = self.relations.collection.find_one(
            {
                "user_id": str(user_id),
                "source_slug": str(source_slug or "").strip().lower(),
                "target_slug": str(target_slug or "").strip().lower(),
                "relation": str(relation or "related_to").strip().lower(),
            }
        )
        if not row:
            raise NotFoundError(
                "That relationship was not found in your knowledge graph.",
                code="relation_not_found",
            )
        source_concept = self.concepts.find_by_slug(user_id, str(row.get("source_slug")))
        target_concept = self.concepts.find_by_slug(user_id, str(row.get("target_slug")))
        evidence = row.get("evidence", []) or []
        return {
            "source": {
                "slug": row.get("source_slug"),
                "label": (source_concept or {}).get("label", row.get("source_slug")),
            },
            "target": {
                "slug": row.get("target_slug"),
                "label": (target_concept or {}).get("label", row.get("target_slug")),
            },
            "relation": row.get("relation", "related_to"),
            "label": RELATION_PHRASES.get(row.get("relation", ""), "relates to"),
            "direction": f"{row.get('source_slug')} → {row.get('target_slug')}",
            "method": row.get("method", "cooccurrence"),
            "created_by": row.get("method", "cooccurrence"),
            "confidence": float(row.get("confidence", 0.0) or 0.0),
            "verification_status": row.get("verification_status", "uncertain"),
            "weight": float(row.get("weight", 1.0)),
            "evidence_count": int(row.get("evidence_count", len(evidence))),
            "created_at": row.get("created_at"),
            "evidence": [
                {
                    "document_id": item.get("document_id"),
                    "document_title": item.get("document_title", ""),
                    "page_number": item.get("page_number"),
                    "snippet": item.get("snippet", ""),
                    "chunk_id": item.get("chunk_id", ""),
                    "confidence": item.get("confidence"),
                    "verification_status": item.get("verification_status"),
                }
                for item in evidence
            ],
        }

    def set_edge_verification(
        self, user_id: Any, source_slug: str, target_slug: str, relation: str, status: str
    ) -> Dict[str, Any]:
        """Verify or reject an edge; rejected edges stay stored but hidden."""
        from utils.errors import ValidationError

        status = (status or "").strip().lower()
        if status not in ("verified", "inferred", "uncertain", "rejected"):
            raise ValidationError(
                f"Unknown verification status '{status}'.",
                code="invalid_verification_status",
                hint="Supported statuses: verified, inferred, uncertain, rejected.",
            )
        matched = self.relations.update_verification(
            user_id, source_slug, target_slug, relation, status
        )
        if not matched:
            raise NotFoundError(
                "That relationship was not found in your knowledge graph.",
                code="relation_not_found",
            )
        return self.edge_evidence(user_id, source_slug, target_slug, relation)

    # ------------------------------------------------------------------
    # Concept detail
    # ------------------------------------------------------------------
    def concept_detail(self, user_id: Any, slug: str) -> Dict[str, Any]:
        """
        One concept with everything the side panel needs (brief §9):

            Concept / Related concepts / Found in (document, page)
        """
        user_id = str(user_id)
        concept = self.concepts.find_by_slug(user_id, slug)
        if not concept:
            raise NotFoundError(
                f"The concept '{slug}' was not found in your knowledge graph.",
                code="concept_not_found",
            )

        neighbour_rows = self.relations.neighbors(user_id, slug, limit=20)
        related: List[Dict[str, Any]] = []
        for relation in neighbour_rows:
            outgoing = relation["source_slug"] == slug
            other_slug = relation["target_slug"] if outgoing else relation["source_slug"]
            other = self.concepts.find_by_slug(user_id, other_slug)
            related.append(
                {
                    "slug": other_slug,
                    "label": (other or {}).get("label", other_slug),
                    "relation": relation.get("relation", "related_to"),
                    "direction": "outgoing" if outgoing else "incoming",
                    "phrase": RELATION_PHRASES.get(relation.get("relation", ""), "relates to"),
                    "method": relation.get("method", "cooccurrence"),
                    "weight": float(relation.get("weight", 1.0)),
                }
            )

        sources = [
            {
                "document_id": ref.get("document_id"),
                "title": ref.get("document_title", ""),
                "page_number": ref.get("page_number"),
                "snippet": ref.get("snippet", ""),
            }
            for ref in (concept.get("page_refs", []) or [])
        ]

        return {
            "slug": concept["slug"],
            "label": concept.get("label", slug),
            "definition": concept.get("definition", ""),
            "score": float(concept.get("score", 0.0)),
            "occurrences": int(concept.get("occurrences", 0)),
            "document_count": int(concept.get("document_count", 0)),
            "related": related,
            "sources": sources,
        }

    # ------------------------------------------------------------------
    # Learning path (brief §12)
    # ------------------------------------------------------------------
    def learning_path(self, user_id: Any, target: str, *, explain_with_llm: bool = True) -> Dict[str, Any]:
        """
        Suggest what to revise before studying ``target``.

        Ordering is computed here from the graph's ``prerequisite_of`` /
        ``requires`` / ``part_of`` edges (deterministic). The local model may add a
        one-line *reason* per step; when it is unavailable the reasons fall back to
        factual phrasing — the path itself never depends on the model.
        """
        user_id = str(user_id)
        concept = self.concepts.find_by_slug(user_id, target) or self._find_by_label(user_id, target)
        if not concept:
            raise NotFoundError(
                f"The concept '{target}' is not in your knowledge graph yet.",
                code="concept_not_found",
                hint="Upload notes covering this topic, then generate the learning path again.",
            )

        target_slug = concept["slug"]
        target_label = concept.get("label", target_slug)

        # Breadth-first walk over prerequisite edges: foundational topics first,
        # exactly the order a student should revise in.
        steps: List[Dict[str, Any]] = []
        visited = {target_slug}
        frontier = [target_slug]
        while frontier and len(steps) < 12:
            current = frontier.pop(0)
            for edge in self.relations.prerequisites(user_id, current, limit=6):
                prerequisite_slug = edge["source_slug"]
                if prerequisite_slug in visited:
                    continue
                visited.add(prerequisite_slug)
                node = self.concepts.find_by_slug(user_id, prerequisite_slug)
                label = (node or {}).get("label", prerequisite_slug)
                phrase = RELATION_PHRASES.get(edge.get("relation", ""), "a prerequisite of")
                steps.append(
                    {
                        "topic": label,
                        "slug": prerequisite_slug,
                        "relation": edge.get("relation", "prerequisite_of"),
                        "reason": f"{label} {phrase} {target_label} in your notes",
                        "score": float((node or {}).get("score", 0.0)),
                    }
                )
                frontier.append(prerequisite_slug)

        # The target itself is always the final step of the plan.
        steps.append(
            {
                "topic": target_label,
                "slug": target_slug,
                "relation": "target",
                "reason": "the topic you want to study",
                "score": float(concept.get("score", 0.0)),
            }
        )

        note = self._explain_with_llm(target_label, steps) if explain_with_llm else None
        return {
            "target": {"slug": target_slug, "label": target_label},
            "steps": steps,
            "note": note,
            "method": "knowledge graph prerequisites"
            + (" + local model explanation" if note else " (deterministic order)"),
        }

    def _find_by_label(self, user_id: Any, label: str) -> Optional[Dict[str, Any]]:
        for concept in self.concepts.list_for_user(user_id, search=label, limit=20):
            if normalize_for_match(concept.get("label", "")) == normalize_for_match(label):
                return concept
        return None

    def _explain_with_llm(self, target: str, steps: List[Dict[str, Any]]) -> Optional[str]:
        """Optional one-paragraph explanation from the local model."""
        try:
            from services.llm import prompts
            from services.llm.factory import get_llm_service

            llm = get_llm_service(self.settings)
            if not llm.is_available():
                return None
            payload = llm.generate_json(
                prompts.build_learning_path_prompt(
                    target, [{"topic": step["topic"], "reason": step["reason"]} for step in steps]
                ),
                system=prompts.LEARNING_PATH_SYSTEM,
                max_tokens=500,
            )
            if not payload:
                return None
            reasons = payload.get("steps") or []
            for step in steps:
                for item in reasons:
                    if normalize_for_match(str(item.get("topic", ""))) == normalize_for_match(step["topic"]):
                        step["reason"] = str(item.get("reason", step["reason"]))[:160]
            return str(payload.get("note", "") or "")[:400] or None
        except Exception as exc:  # noqa: BLE001 - explanation is optional by design
            logger.warning("LLM learning-path explanation skipped: %s", exc)
            return None


def get_graph_service(settings: Optional[Settings] = None) -> GraphService:
    """Convenience factory used by the graph routes."""
    return GraphService(settings)