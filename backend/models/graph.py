"""
Structured domain types for the knowledge graph (brief §9).

The graph is a separate layer from documents/pages/chunks: concepts are shared
across a user's documents, and every node/edge carries its document/page evidence
so the UI can always justify what it shows. Types are plain (no ODM dependency).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from models.domain import utcnow


class ConceptRecord:
    """One concept in a user's knowledge graph — shared across that user's documents."""

    def __init__(
        self,
        *,
        slug: str,
        label: str,
        normalized: Optional[str] = None,
        score: float = 0.0,
        occurrences: int = 0,
        document_count: int = 0,
        document_ids: Optional[List[str]] = None,
        page_refs: Optional[List[Dict[str, Any]]] = None,
        definition: str = "",
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.slug = slug
        self.label = label
        self.normalized = (normalized or "").lower()
        self.score = float(score)
        self.occurrences = int(occurrences)
        self.document_count = int(document_count)
        self.document_ids = list(document_ids or [])
        self.page_refs = list(page_refs or [])
        self.definition = definition.strip()
        self.created_at = created_at or utcnow()
        self.updated_at = updated_at or utcnow()

    def to_mongo(self) -> Dict[str, Any]:
        return {
            "slug": self.slug,
            "label": self.label,
            "normalized": self.normalized,
            "score": self.score,
            "occurrences": self.occurrences,
            "document_count": self.document_count,
            "document_ids": self.document_ids,
            "page_refs": self.page_refs,
            "definition": self.definition,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_mongo(cls, document: Dict[str, Any]) -> "ConceptRecord":
        return cls(
            slug=document.get("slug", ""),
            label=document.get("label", document.get("slug", "")),
            normalized=document.get("normalized", ""),
            score=float(document.get("score", 0.0)),
            occurrences=int(document.get("occurrences", 0)),
            document_count=int(document.get("document_count", 0)),
            document_ids=list(document.get("document_ids", []) or []),
            page_refs=list(document.get("page_refs", []) or []),
            definition=document.get("definition", "") or "",
            created_at=document.get("created_at"),
            updated_at=document.get("updated_at"),
        )


class ConceptRelation:
    """A typed edge between two concepts (unique per user + source + target + relation)."""

    def __init__(
        self,
        *,
        source_slug: str,
        target_slug: str,
        relation: str,
        method: str = "cooccurrence",
        weight: float = 1.0,
        evidence: Optional[List[Dict[str, Any]]] = None,
        confidence: Optional[float] = None,
        verification_status: Optional[str] = None,
        evidence_count: Optional[int] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.source_slug = source_slug
        self.target_slug = target_slug
        self.relation = relation
        self.method = method
        self.weight = float(weight)
        self.evidence = list(evidence or [])
        self.confidence = (
            float(confidence)
            if confidence is not None
            else default_relation_confidence(method, self.evidence)
        )
        self.verification_status = verification_status or verification_for_method(method)
        self.evidence_count = (
            int(evidence_count) if evidence_count is not None else len(self.evidence)
        )
        self.created_at = created_at or utcnow()
        self.updated_at = updated_at or utcnow()

    def to_mongo(self) -> Dict[str, Any]:
        return {
            "source_slug": self.source_slug,
            "target_slug": self.target_slug,
            "relation": self.relation,
            "method": self.method,
            "weight": self.weight,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "verification_status": self.verification_status,
            "evidence_count": self.evidence_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_mongo(cls, document: Dict[str, Any]) -> "ConceptRelation":
        evidence = list(document.get("evidence", []) or [])
        return cls(
            source_slug=document.get("source_slug", ""),
            target_slug=document.get("target_slug", ""),
            relation=document.get("relation", "related_to"),
            method=document.get("method", "cooccurrence"),
            weight=float(document.get("weight", 1.0)),
            evidence=evidence,
            confidence=document.get("confidence"),
            verification_status=document.get("verification_status"),
            evidence_count=document.get("evidence_count"),
            created_at=document.get("created_at"),
            updated_at=document.get("updated_at"),
        )


@dataclass
class PageReference:
    """Where a concept was seen: document + page + optional snippet."""

    document_id: str
    document_title: str = ""
    page_number: int = 1
    snippet: str = ""


RELATION_TYPES = (
    "related_to",
    "prerequisite_of",
    "part_of",
    "explains",
    "requires",
    "example_of",
    "contrasts_with",
    # --- evidence-based types (Phase: graph accuracy; stored vocabulary only) --
    "is_a",
    "used_for",
    "depends_on",
    "causes",
    # --- structural types (task: hybrid relationship engine) -------------------
    "contains",
    "component_of",
    "type_of",
    "application_of",
    "defines",
    "uses_relation",
)

RELATION_METHODS = ("cooccurrence", "cue_phrase", "rule", "structural", "llm")

#: Explicit, rule-derived, or weak associations. Rule/structural edges are as
#: trustworthy as cue-phrase edges (same text fidelity); only "verified" edges
#: are shown by default.
RELATION_VERIFICATION = ("verified", "inferred", "uncertain")

METHOD_VERIFICATION = {
    "cue_phrase": "verified",
    "rule": "verified",
    "structural": "verified",
    "llm": "inferred",
    "cooccurrence": "uncertain",
    "cooccurrence_definition": "inferred",
    # Edges the user uploaded from their own relationship file are the most
    # authoritative source there is — they are the user's own statement.
    "user_specified": "verified",
}

#: Confidence bands for edges — deterministic functions of method + evidence.
RELATION_CONFIDENCE = {
    "verified_min": 0.75,
    "explicit_rule_min": 0.90,
    "structural_min": 0.85,
    "inferred_default": 0.55,
    "uncertain_default": 0.30,
}

#: Relation pairs that cannot co-exist between the same ordered pair.
CONTRADICTORY_RELATIONS = frozenset(
    {
        frozenset({"prerequisite_of", "part_of"}),
        frozenset({"is_a", "contrasts_with"}),
        frozenset({"causes", "contrasts_with"}),
        frozenset({"example_of", "contrasts_with"}),
    }
)

RELATION_PHRASES = {
    "related_to": "relates to",
    "prerequisite_of": "is a prerequisite of",
    "part_of": "is part of",
    "explains": "explains",
    "requires": "requires",
    "example_of": "is an example of",
    "contrasts_with": "contrasts with",
    "is_a": "is a",
    "used_for": "is used for",
    "depends_on": "depends on",
    "causes": "causes",
    "contains": "contains",
    "component_of": "is a component of",
    "type_of": "is a type of",
    "application_of": "is an application of",
    "defines": "defines",
    "uses_relation": "uses the relation",
}


def relation_phrase(relation: str) -> str:
    return RELATION_PHRASES.get(relation, "relates to")


def verification_for_method(method: str) -> str:
    """Map the extraction method to a default verification status."""
    return METHOD_VERIFICATION.get((method or "").strip().lower(), "uncertain")


def default_relation_confidence(method: str, evidence: Optional[List[Dict[str, Any]]] = None) -> float:
    """
    Deterministic confidence from method + evidence:

    * explicitly stated (cue phrase with a text snippet): 0.90 Band (rule) —
      "requires/depends_on/contains/is_a/causes" with verbatim evidence,
    * structural (list/heading evidence): 0.85 Band,
    * rule/LLM-derived with evidence: inferred_default (..0.65),
    * weak co-occurrence or missing evidence: uncertain_default.
    """
    norm = (method or "").strip().lower()
    evidence = list(evidence or [])
    has_snippet = any(bool((item or {}).get("snippet")) for item in evidence)
    if norm in ("rule", "cue_phrase") and has_snippet:
        return max(float(RELATION_CONFIDENCE["explicit_rule_min"]),
                   float(RELATION_CONFIDENCE["verified_min"]))
    if norm == "structural" and has_snippet:
        return max(float(RELATION_CONFIDENCE["structural_min"]),
                   float(RELATION_CONFIDENCE["verified_min"]))
    if norm in ("rule", "structural", "cue_phrase"):
        return round((float(RELATION_CONFIDENCE["verified_min"]) + float(RELATION_CONFIDENCE["inferred_default"])) / 2, 2)
    if norm == "llm" and len(evidence) >= 2:
        return float(RELATION_CONFIDENCE["inferred_default"]) + 0.1
    if norm in ("llm", "cooccurrence_definition"):
        return float(RELATION_CONFIDENCE["inferred_default"])
    return float(RELATION_CONFIDENCE["uncertain_default"])


def relations_contradict(relation_a: str, relation_b: str) -> bool:
    """True when two types cannot co-exist on the same ordered pair."""
    pair = frozenset({(relation_a or "").strip().lower(), (relation_b or "").strip().lower()})
    return pair in CONTRADICTORY_RELATIONS


def _validate_relation(relation: str) -> str:
    relation = (relation or "related_to").strip().lower()
    return relation if relation in RELATION_TYPES else "related_to"
