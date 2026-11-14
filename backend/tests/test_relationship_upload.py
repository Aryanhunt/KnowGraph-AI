"""
Relationship-file uploads, including JSON Lines (.jsonl) (brief §9, §25).

A ``.jsonl`` file — one JSON object per line — is a common shape for a
hand-curated edge list and was previously rejected. These tests cover the
parser (pure, no database) and ``POST /api/graph/upload-relations`` end to end,
proving that JSONL is accepted and that the author's relation labels
(including novel ones such as ``branch_of``) survive the import.
"""

import io
import json

from services.relationship_parser import RelationshipParser, _normalize_relation
from tests.helpers import auth_headers, register_user


JSONL_SAMPLE = "\n".join(
    json.dumps(obj)
    for obj in (
        {
            "chapter": "Chapter 1 - Introduction to Artificial Intelligence",
            "source": "Artificial Intelligence",
            "relation": "branch_of",
            "target": "Computer Science",
            "page": 1,
        },
        {
            "chapter": "Chapter 1 - Introduction to Artificial Intelligence",
            "source": "Machine Learning",
            "relation": "is_an_example_of",
            "target": "Artificial Intelligence",
            "page": 3,
        },
    )
)


# ---------------------------------------------------------------------------
# Parser — deterministic, no database
# ---------------------------------------------------------------------------
def test_jsonl_is_an_accepted_relationship_format():
    assert "jsonl" in RelationshipParser.ACCEPTED_EXTENSIONS


def test_jsonl_parses_one_object_per_line():
    rows = RelationshipParser._parse(None, JSONL_SAMPLE)
    assert len(rows) == 2
    first = rows[0]
    assert first["source"] == "Artificial Intelligence"
    assert first["target"] == "Computer Science"
    assert first["relation"] == "branch_of", "a novel relation must be kept verbatim"
    assert first["page"] == 1
    assert first["chapter"].startswith("Chapter 1")


def test_jsonl_skips_a_malformed_line_without_failing():
    text = JSONL_SAMPLE + "\n{ this line is not valid json }\n"
    assert len(RelationshipParser._parse(None, text)) == 2, "only the bad line is dropped"


def test_single_json_object_and_array_still_parse():
    one = json.dumps({"source": "A", "target": "B", "relation": "requires"})
    assert RelationshipParser._parse(None, one)[0]["relation"] == "requires"
    array = json.dumps([{"source": "A", "target": "B", "relation": "is_a"}])
    assert RelationshipParser._parse(None, array)[0]["relation"] == "is_a"


def test_relation_variants_are_normalised_and_novel_types_kept():
    assert _normalize_relation("is_an_example_of") == "example_of"
    assert _normalize_relation("is_an_application_of") == "application_of"
    assert _normalize_relation("has_component") == "contains"
    assert _normalize_relation("branch_of") == "branch_of", "unknown types are not dropped"
    assert _normalize_relation("") == "related_to"


# ---------------------------------------------------------------------------
# Route — end to end
# ---------------------------------------------------------------------------
def _seed_concepts(user_id, labels):
    """Create the concepts the uploaded edges will be matched against."""
    from db.study_repositories import ConceptRepository

    repo = ConceptRepository()
    for label in labels:
        repo.upsert(
            user_id=user_id,
            label=label,
            document_id="seed-document",
            document_title="Seed",
            page_numbers=[1],
            occurrences=2,
            score=1.0,
        )


def _user_id(client, headers):
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.get_data(as_text=True)
    payload = me.get_json()["data"]
    return (payload.get("user") or payload)["id"]


def _upload_relations(client, token, content, filename="edges.jsonl"):
    return client.post(
        "/api/graph/upload-relations",
        data={"file": (io.BytesIO(content.encode("utf-8")), filename)},
        headers=auth_headers(token),
        content_type="multipart/form-data",
    )


def test_upload_jsonl_relations_stores_edges(client, clean_mongo):
    _, token = register_user(client)
    user_id = _user_id(client, auth_headers(token))
    _seed_concepts(
        user_id, ["Artificial Intelligence", "Computer Science", "Machine Learning"]
    )

    response = _upload_relations(client, token, JSONL_SAMPLE)
    assert response.status_code == 200, response.get_data(as_text=True)
    data = response.get_json()["data"]
    assert data["rows_parsed"] == 2
    assert data["edges_resolved"] == 2
    assert data["edges_stored"] == 2

    from db.study_repositories import RelationRepository

    stored = RelationRepository().list_for_user(user_id)
    by_pair = {(row["source_slug"], row["target_slug"]): row for row in stored}

    branch = by_pair[("artificial-intelligence", "computer-science")]
    assert branch["relation"] == "branch_of", "novel relation preserved"
    assert branch["method"] == "user_specified"
    assert branch["verification_status"] == "verified"
    assert branch["confidence"] == 0.90
    # The per-edge page from the JSONL is kept as evidence (provenance).
    assert any(item.get("page_number") == 1 for item in branch.get("evidence", []))

    example = by_pair[("machine-learning", "artificial-intelligence")]
    assert example["relation"] == "example_of", "is_an_example_of normalised"


def test_upload_jsonl_reports_unmatched_labels(client, clean_mongo):
    _, token = register_user(client)
    user_id = _user_id(client, auth_headers(token))
    _seed_concepts(user_id, ["Computer Science"])

    text = json.dumps(
        {
            "source": "Nonexistent Concept",
            "relation": "branch_of",
            "target": "Computer Science",
            "page": 1,
        }
    )
    response = _upload_relations(client, token, text)
    assert response.status_code == 200, response.get_data(as_text=True)
    data = response.get_json()["data"]
    assert data["edges_stored"] == 0
    assert data["edges_unresolved"] == 1
    assert "Nonexistent Concept" in data["unmatched_sources"]
