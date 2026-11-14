"""
Search, compare, research-mode and analytics behaviour (brief §11–§15, §25).

Hybrid ranking, score-band mapping, set comparisons and the "Not found in
document" contract are all asserted exactly, because the UI shows them verbatim.
"""

from services.compare_service import CompareService
from services.search_service import SearchService
from utils.text import normalize_for_match


def test_search_score_bands_are_documented_and_ordered(client, clean_mongo):
    """The /api/search contract: scores are real, bands have declared thresholds."""
    from routes.search_routes import BAND_HIGH, BAND_MEDIUM, relevance_band

    assert 0 < BAND_MEDIUM < BAND_HIGH
    assert relevance_band(None) == "Unknown"
    assert relevance_band(BAND_HIGH + 1) == "High"
    assert relevance_band(BAND_MEDIUM) == "Medium"
    assert relevance_band(0.0) == "Low"
    assert relevance_band(BAND_HIGH) == "High"


def test_search_requires_a_query(client, clean_mongo):
    from tests.helpers import register_user

    _, token = register_user(client)
    response = client.post("/api/search", json={"query": "   "},
                           headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "empty_query"


def test_search_modes_rejected_when_unknown(client, clean_mongo):
    from tests.helpers import register_user

    _, token = register_user(client)
    response = client.post("/api/search", json={"query": "BCNF", "mode": "telepathy"},
                           headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 400


def test_rrf_merge_prefers_overlap():
    """Reciprocal-rank fusion must rank items appearing in both lists first."""
    from services.search_service import SearchService, SearchResult

    def hit(chunk_id, score):
        return SearchResult(
            document_id="d", document_title="T", page_number=1, chunk_id=chunk_id,
            text="t", source_type="semantic", score=score, metadata={},
        )

    service = SearchService(settings=None)
    merged = service._merge(
        [hit("a", 0.9), hit("b", 0.8)],
        [
            {"_id": "b", "document_id": "d", "page_number": 1, "text": "t",
             "keyword_score": 2.0, "metadata": {}},
            {"_id": "c", "document_id": "d", "page_number": 1, "text": "t",
             "keyword_score": 5.0, "metadata": {}},
        ],
        top_k=3,
        title_map={"d": "T"},
        mode="hybrid",
    )
    assert merged[0].chunk_id == "b", "the item in both lists must win"
    assert all(item.source_type == "hybrid" for item in merged)
    assert all(item.score is not None for item in merged)


def test_comparison_set_operations():
    """Common/unique topics are exact set operations (brief §13)."""
    topic_sets = {
        "a": {"normalization": "Normalization", "bcnf": "BCNF"},
        "b": {"normalization": "Normalization", "tcp": "TCP"},
    }
    common = CompareService._common_topics(topic_sets)
    assert [row["topic"] for row in common] == ["Normalization"]
    unique = CompareService._unique_topics(topic_sets)
    by_doc = {row["document_id"]: row["topics"] for row in unique}
    assert by_doc["a"] == ["BCNF"]
    assert by_doc["b"] == ["TCP"]


def test_compare_route_requires_two_documents(client, clean_mongo):
    from tests.helpers import register_user

    _, token = register_user(client)
    response = client.post("/api/compare", json={"document_ids": ["only-one"]},
                           headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 400


def test_research_fields_default_to_not_found():
    """The research panel must never guess a field (brief §14)."""
    from services.research_service import _missing, NOT_FOUND

    missing = _missing()
    assert missing["found"] is False
    assert missing["value"] == NOT_FOUND
    assert "Not found in document" in NOT_FOUND


def test_knowledge_gap_labels_use_thresholds():
    """The five analytics labels follow the documented constants exactly."""
    from services.analytics_service import AnalyticsService, LABEL_FREQUENTLY_MISSED, LABEL_STRONG

    assert AnalyticsService._label_for(attempts=0, accuracy=None, wrong=0, days_since=None) \
        == "Not Yet Studied"
    assert AnalyticsService._label_for(attempts=5, accuracy=0.9, wrong=0, days_since=1) \
        == LABEL_STRONG
    assert AnalyticsService._label_for(attempts=5, accuracy=0.2, wrong=4, days_since=1) \
        == LABEL_FREQUENTLY_MISSED
    # Few answers: recency wins over a shaky accuracy claim.
    assert AnalyticsService._label_for(attempts=2, accuracy=0.5, wrong=1, days_since=3) \
        == "Recently Studied"


def test_normalize_for_match_is_stable():
    assert normalize_for_match("BCNF!") == "bcnf"
    assert normalize_for_match("Functional-Dependency") == "functional dependency"
