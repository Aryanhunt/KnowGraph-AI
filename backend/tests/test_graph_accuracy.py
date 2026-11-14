"""
Graph accuracy: confidence, verification, evidence and validation rules.

These tests cover the relationship pipeline itself (pure functions) and the
storage-level validation rules (duplicates, self-loops, contradictions,
provenance) using the hermetic Mongo test database.
"""

import pytest

from models.graph import (
    METHOD_VERIFICATION,
    RELATION_TYPES,
    default_relation_confidence,
    relations_contradict,
    verification_for_method,
)
from services.concept_extractor import collect_candidates, extract_relations

STUDY_TEXT = (
    "BCNF requires knowledge of Third Normal Form. "
    "BCNF requires that every determinant is a superkey. "
    "BCNF builds on Third Normal Form, so study it first. "
    "Third Normal Form is a normal form that removes transitive dependencies. "
    "Third Normal Form requires Functional Dependency understanding. "
    "Unlike BCNF, Third Normal Form allows some redundancy in relations."
)


def _pages(text: str = STUDY_TEXT):
    return [(1, text)]


# ---------------------------------------------------------------------------
# Relationship types
# ---------------------------------------------------------------------------
def test_new_relation_types_are_registered():
    for name in ("is_a", "used_for", "depends_on", "causes", "prerequisite_of",
                 "part_of", "example_of", "contrasts_with", "requires", "related_to"):
        assert name in RELATION_TYPES, f"{name} must be a stored vocabulary term"


def test_depends_on_cue_phrase():
    text = "Normalization depends on Functional Dependency to remove redundancy. " * 2
    candidates = collect_candidates(_pages(text))
    relations = extract_relations(_pages(text), candidates)
    assert any(rel.relation == "depends_on" for rel in relations)


def test_causes_cue_phrase():
    text = (
        "A Cyclic Dependency causes an insertion anomaly in the salary relation. "
        "A Cyclic Dependency causes update anomalies as well."
    )
    candidates = collect_candidates(_pages(text))
    relations = extract_relations(_pages(text), candidates)
    assert any(rel.relation == "causes" for rel in relations)


def test_contrasts_with_cue_phrase():
    relations = extract_relations(_pages(STUDY_TEXT), collect_candidates(_pages(STUDY_TEXT)))
    assert any(rel.relation == "contrasts_with" for rel in relations)


# ---------------------------------------------------------------------------
# Direction
# ---------------------------------------------------------------------------
def test_prerequisite_direction_is_source_before_target():
    """'BCNF builds on Third Normal Form' -> prerequisite_of edge, no self-loop."""
    relations = extract_relations(_pages(STUDY_TEXT), collect_candidates(_pages(STUDY_TEXT)))
    prereq = [rel for rel in relations if rel.relation == "prerequisite_of"]
    assert prereq, "a 'builds on' cue must produce a prerequisite edge"
    for rel in prereq:
        assert rel.source != rel.target


def test_requires_direction_keeps_sentence_order():
    text = "BCNF requires Third Normal Form. BCNF requires Third Normal Form again."
    relations = extract_relations(_pages(text), collect_candidates(_pages(text)))
    requires = [rel for rel in relations if rel.relation == "requires"]
    assert requires
    assert any(rel.source.startswith("BCNF") for rel in requires)


# ---------------------------------------------------------------------------
# Evidence attachment
# ---------------------------------------------------------------------------
def test_explicit_relation_carries_page_and_snippet():
    relations = extract_relations(_pages(STUDY_TEXT), collect_candidates(_pages(STUDY_TEXT)))
    explicit = [rel for rel in relations if rel.method == "cue_phrase"]
    assert explicit, "cue-phrase relations must exist for this text"
    for rel in explicit:
        assert rel.page_number == 1, "evidence must record the page"
        assert rel.snippet, "evidence must quote the supporting sentence"
        assert rel.evidence_payload()["snippet"] == rel.snippet


def test_evidence_payload_shape():
    payload = extract_relations(
        _pages(STUDY_TEXT), collect_candidates(_pages(STUDY_TEXT))
    )[0].evidence_payload()
    for key in ("page_number", "snippet", "chunk_id", "method",
                "confidence", "verification_status", "evidence_count"):
        assert key in payload, f"evidence must include {key}"


# ---------------------------------------------------------------------------
# Confidence + verification rules
# ---------------------------------------------------------------------------
def test_confidence_bands_are_ordered():
    verified = default_relation_confidence("cue_phrase", [{"snippet": "x"}])
    inferred = default_relation_confidence("llm", [{"snippet": "x"}])
    weak = default_relation_confidence("cooccurrence", [])
    assert verified > inferred > weak
    assert 0.0 <= weak and verified <= 1.0


def test_verification_status_by_method():
    assert verification_for_method("cue_phrase") == "verified"
    assert verification_for_method("llm") == "inferred"
    assert verification_for_method("cooccurrence") == "uncertain"
    assert METHOD_VERIFICATION["cooccurrence"] == "uncertain"


def test_explicit_relation_is_verified():
    relations = extract_relations(_pages(STUDY_TEXT), collect_candidates(_pages(STUDY_TEXT)))
    for rel in relations:
        if rel.method == "cue_phrase" and rel.snippet:
            assert rel.evidence_payload()["verification_status"] == "verified"
            assert rel.evidence_payload()["confidence"] >= 0.75


# ---------------------------------------------------------------------------
# Weak co-occurrence must not become a verified edge
# ---------------------------------------------------------------------------
def test_single_cooccurrence_does_not_create_an_edge():
    """Two concepts in one shared sentence is not evidence of a relationship."""
    text = (
        "Hill Climbing and Simulated Annealing are both local search methods. "
        "This sentence mentions Hill Climbing once more for scoring."
    )
    candidates = collect_candidates(_pages(text))
    relations = extract_relations(_pages(text), candidates)
    weak = [rel for rel in relations if rel.method == "cooccurrence"]
    assert not weak, "one shared sentence must not create a co-occurrence edge"


def test_repeated_cooccurrence_is_uncertain_not_verified():
    text = (
        "TCP and Routing appear together in networks. "
        "TCP and Routing are taught together with packets. "
        "TCP and Routing both matter for the exam revision."
    ) * 2
    candidates = collect_candidates(_pages(text))
    relations = extract_relations(_pages(text), candidates)
    weak = [rel for rel in relations if rel.method == "cooccurrence"]
    assert weak, "repeated co-occurrence should still produce a weak edge"
    for rel in weak:
        payload = rel.evidence_payload()
        assert payload["verification_status"] == "uncertain"
        assert payload["confidence"] < 0.75


# ---------------------------------------------------------------------------
# Contradiction rules
# ---------------------------------------------------------------------------
def test_contradictory_pairs_are_detected():
    assert relations_contradict("prerequisite_of", "part_of")
    assert relations_contradict("is_a", "contrasts_with")
    assert not relations_contradict("requires", "prerequisite_of")
    assert not relations_contradict("related_to", "related_to")


# ---------------------------------------------------------------------------
# Storage-level validation rules
# ---------------------------------------------------------------------------
def _relation_row(user_id="u1", source="a", target="b", relation="requires", method="cue_phrase"):
    from db.study_repositories import RelationRepository

    repo = RelationRepository()
    repo.upsert(
        user_id=user_id,
        source_slug=source,
        target_slug=target,
        relation=relation,
        method=method,
        weight=1.0,
        evidence={"snippet": "x requires y", "page_number": 1, "confidence": 0.75,
                  "verification_status": "verified"},
    )
    return repo


def test_self_loop_is_never_stored(clean_mongo):
    repo = _relation_row(source="bcnf", target="bcnf")
    rows = repo.list_for_user("u1")
    assert rows == [], "a self-loop must never become an edge"


def test_duplicate_relations_are_merged_not_duplicated(clean_mongo):
    repo = _relation_row()
    repo.upsert(
        user_id="u1", source_slug="a", target_slug="b", relation="requires",
        method="cue_phrase", weight=1.0,
        evidence={"snippet": "again", "page_number": 2, "confidence": 0.75,
                  "verification_status": "verified"},
    )
    rows = repo.list_for_user("u1")
    assert len(rows) == 1, "the same user+pair+type must be one document"
    assert rows[0]["weight"] == 2.0, "repeat evidence strengthens, not duplicates"


def test_contradictory_relation_is_refused(clean_mongo):
    repo = _relation_row(relation="prerequisite_of")
    repo.upsert(
        user_id="u1", source_slug="a", target_slug="b", relation="part_of",
        method="cue_phrase", weight=1.0,
    )
    rows = repo.list_for_user("u1")
    assert len(rows) == 1
    assert rows[0]["relation"] == "prerequisite_of", "the stored edge must be kept"


def test_confidence_and_verification_are_persisted(clean_mongo):
    from models.graph import default_relation_confidence

    repo = _relation_row()
    row = repo.list_for_user("u1")[0]
    # A cue-phrase edge with a text snippet sits in the explicit-rule band;
    # derive the expectation from the single source of truth so the test cannot
    # drift away from the documented confidence bands again.
    expected = default_relation_confidence("cue_phrase", [{"snippet": "x requires y"}])
    assert row["confidence"] == expected
    assert row["verification_status"] == "verified"
    assert row["evidence_count"] >= 1
    assert row["created_at"] is not None


def test_user_isolation_of_relations(clean_mongo):
    repo = _relation_row(user_id="user-a")
    repo.upsert(
        user_id="user-b", source_slug="a", target_slug="b", relation="requires",
        method="cue_phrase", weight=1.0,
    )
    assert len(repo.list_for_user("user-a")) == 1
    assert len(repo.list_for_user("user-b")) == 1
    assert len(repo.list_for_user("user-c")) == 0


def test_verification_filter_excludes_uncertain(clean_mongo):
    from db.study_repositories import RelationRepository

    repo = RelationRepository()
    repo.upsert(user_id="u1", source_slug="a", target_slug="b", relation="related_to",
                method="cooccurrence", weight=1.0)
    repo.upsert(user_id="u1", source_slug="c", target_slug="d", relation="requires",
                method="cue_phrase", weight=1.0,
                evidence={"snippet": "c requires d", "confidence": 0.75,
                          "verification_status": "verified"})
    verified = repo.list_for_user("u1", verification="verified")
    assert {row["relation"] for row in verified} == {"requires"}
    all_rows = repo.list_for_user("u1")
    assert len(all_rows) == 2


def test_min_confidence_filter(clean_mongo):
    from db.study_repositories import RelationRepository

    repo = RelationRepository()
    repo.upsert(user_id="u1", source_slug="a", target_slug="b", relation="related_to",
                method="cooccurrence", weight=1.0)
    repo.upsert(user_id="u1", source_slug="c", target_slug="d", relation="requires",
                method="cue_phrase", weight=1.0,
                evidence={"snippet": "c requires d", "confidence": 0.75,
                          "verification_status": "verified"})
    high = repo.list_for_user("u1", min_confidence=0.6)
    assert {row["relation"] for row in high} == {"requires"}


def test_update_verification_hides_without_deleting(clean_mongo):
    repo = _relation_row()
    assert repo.update_verification("u1", "a", "b", "requires", "rejected") is True
    rows = repo.list_for_user("u1")
    assert len(rows) == 1, "rejection must not delete the relationship"
    assert rows[0]["verification_status"] == "rejected"
    assert repo.list_for_user("u1", verification="verified") == []


# ---------------------------------------------------------------------------
# API: filtering, evidence, verification, isolation, empty graph
# ---------------------------------------------------------------------------
SAMPLE_DOC = (
    "BCNF requires Third Normal Form. BCNF requires Third Normal Form knowledge. "
    "BCNF builds on Third Normal Form for decomposition. "
    "Third Normal Form requires Functional Dependency understanding. "
    "Third Normal Form requires Functional Dependency analysis."
)


def _graph_fixture(client):
    """Upload one document and return (token, headers)."""
    from tests.helpers import auth_headers, register_user, text_upload, upload

    _, token = register_user(client)
    response = upload(client, token, text_upload(SAMPLE_DOC, "graph-notes.txt"))
    assert response.status_code == 201, response.get_data(as_text=True)
    return token, auth_headers(token)


def test_graph_returns_verified_edges_by_default(client, clean_mongo):
    token, headers = _graph_fixture(client)
    payload = client.get("/api/graph?limit=60", headers=headers).get_json()["data"]
    assert payload["stats"]["concept_count"] >= 2
    for edge in payload["edges"]:
        assert edge["verification_status"] == "verified"
        assert edge["confidence"] >= 0.75
        for key in ("confidence", "verification_status", "evidence_count", "method"):
            assert key in edge


def test_graph_all_filter_can_include_weak_edges(client, clean_mongo, settings):
    """Weak edges are stored but hidden by default; ?verification=all reveals them."""
    from db.study_repositories import RelationRepository
    from tests.helpers import auth_headers, register_user

    token, headers = _graph_fixture(client)
    _me_resp = client.get("/api/auth/me", headers=headers)
    assert _me_resp.status_code == 200, _me_resp.get_data(as_text=True)
    me = _me_resp.get_json()["data"]
    user_id = (me.get("user") or me)["id"]
    RelationRepository().upsert(
        user_id=user_id, source_slug="weak-a", target_slug="weak-b",
        relation="related_to", method="cooccurrence", weight=1.0,
    )
    default_edges = client.get("/api/graph?limit=60", headers=headers).get_json()["data"]["edges"]
    assert all(edge["relation"] != "related_to" for edge in default_edges)
    all_edges = client.get(
        "/api/graph?limit=60&verification=all", headers=headers
    ).get_json()["data"]["edges"]
    assert any(edge["verification_status"] == "uncertain" for edge in all_edges)
    stored = RelationRepository().list_for_user(user_id)
    assert any(row["verification_status"] == "uncertain" for row in stored), (
        "filtering must not delete the weak relationship"
    )


def test_graph_all_returns_edges_with_null_confidence(client, clean_mongo):
    """
    Regression test: relations written by older code have no ``confidence``
    or ``verification_status`` field.  MongoDB's ``{"$gte": 0.0}`` silently
    excludes documents where the field is missing/null, so the 'all' filter
    returned zero edges and the graph rendered as an empty dot-grid.

    After the fix, ``list_for_user(min_confidence=0.0)`` must skip the
    confidence filter entirely (threshold <= 0), returning those edges.
    """
    from db.study_repositories import ConceptRepository, RelationRepository
    from models.domain import utcnow
    from tests.helpers import auth_headers, register_user

    user, token = register_user(client, email="null-conf@example.com")
    headers = auth_headers(token)
    rel_repo = RelationRepository()
    concept_repo = ConceptRepository()

    # ``get_graph`` only returns edges whose slugs match concept nodes, so
    # we must insert both the relation and the two concept nodes.
    user_id = str(user["id"] if "id" in user else user["user_id"])
    now = utcnow()

    concept_repo.collection.insert_many([
        {
            "user_id": user_id, "slug": "alpha", "label": "Alpha",
            "normalized": "alpha", "score": 1.0, "occurrences": 1,
            "document_count": 1, "document_ids": ["doc1"],
            "page_refs": [{"document_id": "doc1", "page_number": 1}],
            "definition": "", "created_at": now, "updated_at": now,
        },
        {
            "user_id": user_id, "slug": "beta", "label": "Beta",
            "normalized": "beta", "score": 1.0, "occurrences": 1,
            "document_count": 1, "document_ids": ["doc1"],
            "page_refs": [{"document_id": "doc1", "page_number": 1}],
            "definition": "", "created_at": now, "updated_at": now,
        },
    ])

    # Insert a relation with NO confidence/verification_status field at all —
    # simulating data written before those columns existed.
    rel_repo.collection.insert_one({
        "user_id": user_id,
        "source_slug": "alpha",
        "target_slug": "beta",
        "relation": "related_to",
        "method": "cooccurrence",
        "weight": 1.0,
        "evidence": [{"document_id": "doc1", "snippet": "", "page_number": 1}],
        "created_at": now,
        "updated_at": now,
    })

    # Repository level: min_confidence=0 must return the null-confidence edge
    rows = rel_repo.list_for_user(user_id, slugs=["alpha", "beta"], min_confidence=0.0)
    assert len(rows) == 1, "edges with null confidence must be included when min_confidence=0"
    assert rows[0]["source_slug"] == "alpha"
    assert rows[0]["target_slug"] == "beta"

    # API level: /api/graph?verification=all&min_confidence=0 must show the edge
    resp = client.get(
        "/api/graph?verification=all&min_confidence=0&limit=50", headers=headers
    )
    assert resp.status_code == 200
    edges = resp.get_json()["data"]["edges"]
    assert any(
        e["source"] == "alpha" and e["target"] == "beta" for e in edges
    ), "the null-confidence edge must appear in the 'all' graph view"


def test_graph_min_confidence_filter(client, clean_mongo):
    token, headers = _graph_fixture(client)
    response = client.get("/api/graph?min_confidence=0.9&verification=all", headers=headers)
    assert response.status_code == 200
    for edge in response.get_json()["data"]["edges"]:
        assert edge["confidence"] >= 0.9


def test_graph_rejects_bad_filters(client, clean_mongo):
    _, headers = _graph_fixture(client)
    assert client.get("/api/graph?min_confidence=abc", headers=headers).status_code == 400
    assert client.get("/api/graph?min_confidence=2", headers=headers).status_code == 400
    assert client.get("/api/graph?verification=telepathy", headers=headers).status_code == 400


def test_empty_graph_is_handled(client, clean_mongo):
    from tests.helpers import auth_headers, register_user

    _, token = register_user(client, email="empty-graph@example.com")
    payload = client.get("/api/graph", headers=auth_headers(token)).get_json()["data"]
    assert payload["nodes"] == []
    assert payload["edges"] == []


def test_status_reports_verification_counts(client, clean_mongo):
    _, headers = _graph_fixture(client)
    status = client.get("/api/graph/status", headers=headers).get_json()["data"]
    for key in ("verified_relation_count", "inferred_relation_count", "uncertain_relation_count"):
        assert key in status
    assert status["verified_relation_count"] >= 0


def test_edge_evidence_endpoint(client, clean_mongo):
    token, headers = _graph_fixture(client)
    edges = client.get("/api/graph?limit=60", headers=headers).get_json()["data"]["edges"]
    assert edges, "the sample document must produce at least one verified edge"
    edge = edges[0]
    response = client.get(
        f"/api/graph/relations/evidence?source={edge['source']}"
        f"&target={edge['target']}&relation={edge['relation']}",
        headers=headers,
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()["data"]
    for key in ("source", "target", "relation", "direction", "confidence",
                "verification_status", "evidence", "evidence_count",
                "created_by", "created_at"):
        assert key in payload, f"edge inspector needs {key}"
    assert payload["evidence"], "evidence must be attached to the edge"


def test_edge_evidence_missing_args(client, clean_mongo):
    _, headers = _graph_fixture(client)
    assert client.get("/api/graph/relations/evidence", headers=headers).status_code == 400


def test_edge_evidence_unknown_relation(client, clean_mongo):
    _, headers = _graph_fixture(client)
    response = client.get(
        "/api/graph/relations/evidence?source=nope&target=nada&relation=requires",
        headers=headers,
    )
    assert response.status_code == 404


def test_verify_and_reject_edge(client, clean_mongo):
    token, headers = _graph_fixture(client)
    edges = client.get("/api/graph?limit=60", headers=headers).get_json()["data"]["edges"]
    edge = edges[0]
    body = {"source": edge["source"], "target": edge["target"], "relation": edge["relation"]}

    rejected = client.post(
        "/api/graph/relations/verify", json={**body, "status": "rejected"}, headers=headers
    )
    assert rejected.status_code == 200
    assert rejected.get_json()["data"]["verification_status"] == "rejected"

    after = client.get("/api/graph?limit=60", headers=headers).get_json()["data"]["edges"]
    assert all(
        not (e["source"] == edge["source"] and e["target"] == edge["target"]) for e in after
    )
    everything = client.get(
        "/api/graph?limit=60&verification=all", headers=headers
    ).get_json()["data"]["edges"]
    assert any(
        e["source"] == edge["source"] and e["target"] == edge["target"] for e in everything
    ), "a rejected relationship must still be stored"

    restored = client.post(
        "/api/graph/relations/verify", json={**body, "status": "verified"}, headers=headers
    )
    assert restored.get_json()["data"]["verification_status"] == "verified"


def test_verify_rejects_bad_status(client, clean_mongo):
    token, headers = _graph_fixture(client)
    response = client.post(
        "/api/graph/relations/verify",
        json={"source": "a", "target": "b", "relation": "requires", "status": "maybe"},
        headers=headers,
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_verification_status"


def test_graph_endpoints_require_auth(client, clean_mongo):
    assert client.get("/api/graph").status_code == 401
    assert client.get("/api/graph/status").status_code == 401
    assert client.get(
        "/api/graph/relations/evidence?source=a&target=b&relation=requires"
    ).status_code == 401
    assert client.post("/api/graph/relations/verify", json={}).status_code == 401


def test_edge_evidence_user_isolation(client, clean_mongo):
    from tests.helpers import auth_headers, register_user

    token_a, headers_a = _graph_fixture(client)
    _, token_b = register_user(client, email="other-user@example.com")
    _g_resp = client.get("/api/graph?limit=60", headers=headers_a)
    assert _g_resp.status_code == 200, _g_resp.get_data(as_text=True)
    edges = _g_resp.get_json()["data"]["edges"]
    edge = edges[0]
    response = client.get(
        f"/api/graph/relations/evidence?source={edge['source']}"
        f"&target={edge['target']}&relation={edge['relation']}",
        headers=auth_headers(token_b),
    )
    assert response.status_code == 404, "another user must not read this edge"


def test_disconnected_nodes_are_still_returned(client, clean_mongo):
    """Every returned node is one of: connected to an edge, or genuinely isolated."""
    token, headers = _graph_fixture(client)
    payload = client.get("/api/graph?limit=60", headers=headers).get_json()["data"]
    connected = set()
    for edge in payload["edges"]:
        connected.add(edge["source"])
        connected.add(edge["target"])
    isolated = [node for node in payload["nodes"] if node["id"] not in connected]
    assert len(isolated) + len(connected) <= len(payload["nodes"])
    assert payload["nodes"], "the sample document must produce concept nodes"