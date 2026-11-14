"""
OCR review & correction API tests (Phases 5-6).

Covers: page listing/report, save/reset correction, mark reviewed, ownership
isolation, invalid ids, reindex behaviour and idempotency. The suite runs with
hashing embeddings + numpy vector store, so reindexing is fully offline.
"""

from tests.helpers import (
    auth_headers,
    register_user,
    text_upload,
    upload,
)

SAMPLE_TEXT = (
    "Functional Dependency\\n\\n"
    "A functional dependency X -> Y means X determines Y. "
    "BCNF requires every determinant to be a superkey.\\n"
)


def _upload_document(client, token, text=SAMPLE_TEXT):
    response = upload(client, token, text_upload(text))
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()["data"]


def test_review_report_lists_pages(client, clean_mongo):
    _, token = register_user(client)
    document = _upload_document(client, token)

    response = client.get(
        f"/api/documents/{document['id']}/ocr/review", headers=auth_headers(token)
    )
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["document"]["id"] == document["id"]
    assert payload["summary"]["total"] >= 1
    assert len(payload["pages"]) == payload["summary"]["total"]
    for page in payload["pages"]:
        assert "quality_label" in page
        assert "corrected_text" in page
        assert "effective_text" in page
        assert page["original_text"] == page["text"]


def test_single_page_report(client, clean_mongo):
    _, token = register_user(client)
    document = _upload_document(client, token)

    response = client.get(
        f"/api/documents/{document['id']}/ocr/review/1", headers=auth_headers(token)
    )
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["page_number"] == 1
    assert payload["has_image"] is False  # digital text -> no rendered image


def test_save_correction_and_effective_text(client, clean_mongo):
    _, token = register_user(client)
    document = _upload_document(client, token)

    corrected = "A corrected sentence about functional dependency with more detail."
    response = client.put(
        f"/api/documents/{document['id']}/ocr/review/1/correction",
        json={"corrected_text": corrected},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    page = response.get_json()["data"]
    assert page["corrected_text"] == corrected
    assert page["effective_text"] == corrected
    assert page["correction_status"] == "corrected"
    assert page["correction_version"] == 1
    assert page["needs_reindex"] is True
    assert page["original_text"] and page["original_text"] != corrected


def test_correction_version_increments(client, clean_mongo):
    _, token = register_user(client)
    document = _upload_document(client, token)
    url = f"/api/documents/{document['id']}/ocr/review/1/correction"

    client.put(url, json={"corrected_text": "first correction version here"},
               headers=auth_headers(token))
    response = client.put(url, json={"corrected_text": "second correction version here"},
                          headers=auth_headers(token))
    assert response.get_json()["data"]["correction_version"] == 2


def test_empty_correction_rejected(client, clean_mongo):
    _, token = register_user(client)
    document = _upload_document(client, token)
    response = client.put(
        f"/api/documents/{document['id']}/ocr/review/1/correction",
        json={"corrected_text": "   "},
        headers=auth_headers(token),
    )
    assert response.status_code == 400


def test_reset_correction(client, clean_mongo):
    _, token = register_user(client)
    document = _upload_document(client, token)
    url = f"/api/documents/{document['id']}/ocr/review/1/correction"
    client.put(url, json={"corrected_text": "temporary correction text"},
               headers=auth_headers(token))

    response = client.delete(url, headers=auth_headers(token))
    assert response.status_code == 200
    page = response.get_json()["data"]
    assert page["corrected_text"] == ""
    assert page["correction_status"] == ""
    assert page["effective_text"] == page["original_text"]


def test_mark_reviewed(client, clean_mongo):
    _, token = register_user(client)
    document = _upload_document(client, token)
    response = client.post(
        f"/api/documents/{document['id']}/ocr/review/1/review",
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    page = response.get_json()["data"]
    assert page["correction_status"] == "reviewed"
    assert page["reviewed_by"]


def test_user_isolation_on_review_endpoints(client, clean_mongo):
    _, token_a = register_user(client, email="user-a@example.com")
    _, token_b = register_user(client, email="user-b@example.com")
    document = _upload_document(client, token_a)

    base = f"/api/documents/{document['id']}"
    assert client.get(f"{base}/ocr/review", headers=auth_headers(token_b)).status_code == 404
    assert client.get(f"{base}/ocr/review/1", headers=auth_headers(token_b)).status_code == 404
    assert (
        client.put(
            f"{base}/ocr/review/1/correction",
            json={"corrected_text": "hijack attempt text"},
            headers=auth_headers(token_b),
        ).status_code
        == 404
    )
    assert (
        client.post(f"{base}/ocr/reindex", headers=auth_headers(token_b)).status_code == 404
    )


def test_invalid_page_number_handled(client, clean_mongo):
    _, token = register_user(client)
    document = _upload_document(client, token)
    assert (
        client.get(
            f"/api/documents/{document['id']}/ocr/review/999",
            headers=auth_headers(token),
        ).status_code
        == 404
    )


def test_invalid_document_id_handled(client, clean_mongo):
    _, token = register_user(client)
    assert (
        client.get(
            "/api/documents/not-a-valid-id/ocr/review", headers=auth_headers(token)
        ).status_code
        == 400
    )


def test_review_requires_auth(client, clean_mongo):
    _, token = register_user(client)
    document = _upload_document(client, token)
    assert client.get(f"/api/documents/{document['id']}/ocr/review").status_code == 401
    assert (
        client.put(
            f"/api/documents/{document['id']}/ocr/review/1/correction",
            json={"corrected_text": "x"},
        ).status_code
        == 401
    )


def test_reindex_after_correction_uses_effective_text(client, clean_mongo):
    """After saving a correction + reindexing, chunks must contain corrected text."""
    from db.repositories import ChunkRepository

    _, token = register_user(client)
    document = _upload_document(client, token)
    doc_id = document["id"]

    corrected = "Corrected content about functional dependency and BCNF rules."
    response = client.put(
        f"/api/documents/{doc_id}/ocr/review/1/correction",
        json={"corrected_text": corrected},
        headers=auth_headers(token),
    )
    assert response.status_code == 200

    response = client.post(
        f"/api/documents/{doc_id}/ocr/reindex", headers=auth_headers(token)
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()["data"]
    assert payload["chunk_count"] >= 1

    chunks = ChunkRepository().list_for_document(doc_id)
    assert chunks, "reindex must create chunks"
    joined = " ".join(chunk["text"] for chunk in chunks)
    assert corrected in joined

    # The needs_reindex flag is cleared after a successful reindex.
    review = client.get(
        f"/api/documents/{doc_id}/ocr/review", headers=auth_headers(token)
    ).get_json()["data"]
    assert review["summary"]["needs_reindex"] == 0


def test_reindex_is_idempotent(client, clean_mongo):
    """Running reindex twice must not duplicate chunks or vectors."""
    from db.repositories import ChunkRepository

    _, token = register_user(client)
    document = _upload_document(client, token)
    doc_id = document["id"]

    client.put(
        f"/api/documents/{doc_id}/ocr/review/1/correction",
        json={"corrected_text": "idempotency check correction text"},
        headers=auth_headers(token),
    )
    client.post(f"/api/documents/{doc_id}/ocr/reindex", headers=auth_headers(token))
    first_count = len(ChunkRepository().list_for_document(doc_id))
    response = client.post(f"/api/documents/{doc_id}/ocr/reindex", headers=auth_headers(token))
    assert response.status_code == 200
    second_count = len(ChunkRepository().list_for_document(doc_id))
    assert first_count == second_count


def test_failed_reindex_preserves_correction(client, clean_mongo, monkeypatch):
    """An embedding outage must not lose the saved correction."""
    _, token = register_user(client)
    document = _upload_document(client, token)
    doc_id = document["id"]

    corrected = "correction survives an embedding outage"
    client.put(
        f"/api/documents/{doc_id}/ocr/review/1/correction",
        json={"corrected_text": corrected},
        headers=auth_headers(token),
    )

    def broken_embed(self, texts):  # noqa: ARG002
        from services.embeddings.base import EmbeddingResult

        return EmbeddingResult(vectors=[], ok=False, error="simulated outage")

    monkeypatch.setattr(
        "services.embeddings.hashing_embeddings.HashingEmbeddingService.embed_texts",
        broken_embed,
        raising=True,
    )
    response = client.post(f"/api/documents/{doc_id}/ocr/reindex", headers=auth_headers(token))
    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "reindex_embedding_failed"

    # Correction preserved + still flagged for reindex.
    review = client.get(
        f"/api/documents/{doc_id}/ocr/review/1", headers=auth_headers(token)
    ).get_json()["data"]
    assert review["corrected_text"] == corrected
    assert review["needs_reindex"] is True