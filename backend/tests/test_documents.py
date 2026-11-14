"""
Upload validation, per-user isolation and the document lifecycle (brief §21, §25).

The pipeline runs synchronously in tests (``PROCESSING_SYNC=true``), so uploaded
fixtures are processed inline and status assertions are deterministic.
"""

from tests.helpers import (
    auth_headers,
    make_scanned_pdf_bytes,
    pdf_upload,
    register_user,
    scanned_pdf_upload,
    text_upload,
    upload,
)

SAMPLE_TEXT = (
    "Functional Dependency\n\n"
    "A functional dependency X -> Y means X determines Y. "
    "BCNF requires every determinant to be a superkey.\n"
)


def _upload_text(client, token, text=SAMPLE_TEXT, filename="notes.txt"):
    response = upload(client, token, text_upload(text, filename))
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()["data"]


def test_upload_and_process_text_file(client, clean_mongo):
    _, token = register_user(client)
    document = _upload_text(client, token)
    assert document["processing_status"] == "completed"
    assert document["page_count"] >= 1
    assert document["chunk_count"] >= 1
    assert document["summary"], "pipeline must leave a summary even without Ollama"

    response = client.get(f"/api/documents/{document['id']}",
                          headers=auth_headers(token))
    assert response.status_code == 200


def test_upload_pdf_text_extraction(client, clean_mongo):
    _, token = register_user(client)
    response = upload(client, token, pdf_upload("Boyce-Codd Normal Form\n\n" + SAMPLE_TEXT))
    assert response.status_code == 201
    document = response.get_json()["data"]
    assert document["processing_status"] == "completed"
    assert document["page_count"] == 1
    assert document["ocr_used"] is False, "digital pages must not trigger OCR"


def test_upload_scanned_pdf_runs_ocr(client, clean_mongo):
    _, token = register_user(client)
    response = upload(client, token, scanned_pdf_upload(), subject="Scans")
    assert response.status_code == 201, response.get_data(as_text=True)
    document = response.get_json()["data"]
    # Tesseract is installed, so the image-only PDF is transcribed automatically
    # without the user having to ask for OCR.
    assert document["processing_status"] == "completed"
    assert document["ocr_used"] is True
    assert document["ocr_page_count"] >= 1
    assert document["page_count"] >= 1


def test_upload_image_ocr(client, clean_mongo):
    """Images follow the same OCR path as scanned pages (brief §3)."""
    from io import BytesIO
    from PIL import Image, ImageDraw

    _, token = register_user(client)
    image = Image.new("RGB", (600, 160), "white")
    ImageDraw.Draw(image).text((20, 20), "Normalization reduces data redundancy.", fill="black")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    response = client.post(
        "/api/documents",
        data={"file": (buffer, "notes-photo.png")},
        headers=auth_headers(token),
        content_type="multipart/form-data",
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    document = response.get_json()["data"]
    assert document["processing_status"] == "completed"
    assert document["ocr_used"] is True


def test_unsupported_file_type_rejected(client, clean_mongo):
    _, token = register_user(client)
    from io import BytesIO

    response = client.post(
        "/api/documents",
        data={"file": (BytesIO(b"not really an archive"), "evil.zip")},
        headers=auth_headers(token),
        content_type="multipart/form-data",
    )
    assert response.status_code in (400, 415)
    assert "unsupported" in response.get_json()["error"]["code"]


def test_empty_file_rejected(client, clean_mongo):
    _, token = register_user(client)
    from io import BytesIO

    response = client.post(
        "/api/documents",
        data={"file": (BytesIO(b""), "empty.txt")},
        headers=auth_headers(token),
        content_type="multipart/form-data",
    )
    assert response.status_code in (400, 422)


def test_missing_file_rejected(client, clean_mongo):
    _, token = register_user(client)
    response = client.post(
        "/api/documents", data={}, headers=auth_headers(token),
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "missing_file"


def test_corrupt_pdf_does_not_crash(client, clean_mongo):
    """A broken PDF must fail *recorded*, not with a 500 (brief §22)."""
    _, token = register_user(client)
    from io import BytesIO

    response = client.post(
        "/api/documents",
        data={"file": (BytesIO(b"%PDF-1.4 this is not a real pdf"), "broken.pdf")},
        headers=auth_headers(token),
        content_type="multipart/form-data",
    )
    assert response.status_code == 201  # queued first, like a real upload
    document = response.get_json()["data"]
    assert document["processing_status"] in ("failed", "completed")
    if document["processing_status"] == "failed":
        assert document["processing_error"], "failure must explain itself"

    follow_up = client.get(f"/api/documents/{document['id']}",
                           headers=auth_headers(token))
    assert follow_up.status_code == 200


def test_per_user_isolation(client, clean_mongo):
    """One user can never read, edit or delete another user's documents (brief §21)."""
    _, token_alice = register_user(client, email="alice@example.com")
    _, token_bob = register_user(client, email="bob@example.com")

    document = _upload_text(client, token_alice)
    document_id = document["id"]

    assert client.get(f"/api/documents/{document_id}",
                      headers=auth_headers(token_bob)).status_code == 404
    assert client.patch(f"/api/documents/{document_id}", json={"title": "Hijacked"},
                        headers=auth_headers(token_bob)).status_code == 404
    assert client.delete(f"/api/documents/{document_id}",
                         headers=auth_headers(token_bob)).status_code == 404
    assert client.get(f"/api/documents/{document_id}/pages",
                      headers=auth_headers(token_bob)).status_code == 404

    # The owner still sees it.
    assert client.get(f"/api/documents/{document_id}",
                      headers=auth_headers(token_alice)).status_code == 200


def test_list_filters_and_pagination(client, clean_mongo):
    _, token = register_user(client)
    _upload_text(client, token, filename="dbms.txt")
    _upload_text(client, token, filename="networks.txt")

    listing = client.get("/api/documents?page=1&page_size=1",
                         headers=auth_headers(token)).get_json()
    assert listing["meta"]["total"] >= 2
    assert len(listing["data"]) == 1

    filtered = client.get("/api/documents?status=completed",
                          headers=auth_headers(token)).get_json()
    assert filtered["meta"]["total"] >= 2
    assert all(item["processing_status"] == "completed" for item in filtered["data"])

    searched = client.get("/api/documents?search=dbms",
                          headers=auth_headers(token)).get_json()
    assert any("dbms" in item["title"].lower() for item in searched["data"])


def test_update_title_and_subject(client, clean_mongo):
    _, token = register_user(client)
    document = _upload_text(client, token)

    response = client.patch(
        f"/api/documents/{document['id']}",
        json={"title": "DBMS Unit 3", "subject": "DBMS", "tags": ["normalization"]},
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["title"] == "DBMS Unit 3"
    assert payload["subject"] == "DBMS"
    assert "normalization" in payload["tags"]


def test_delete_removes_everything(client, clean_mongo):
    """Deleting a document removes pages, chunks and vectors with it (brief §5)."""
    _, token = register_user(client)
    document = _upload_text(client, token)
    document_id = document["id"]

    response = client.delete(f"/api/documents/{document_id}",
                             headers=auth_headers(token))
    assert response.status_code == 200
    removed = response.get_json()["data"]["removed"]
    assert removed["pages"] >= 1
    assert removed["chunks"] >= 1
    assert removed["vectors"] >= 1
    assert removed["file_removed"] is True
    assert "quizzes" in removed, "the delete report must account for quizzes"

    assert client.get(f"/api/documents/{document_id}",
                      headers=auth_headers(token)).status_code == 404


def test_delete_cascades_to_quizzes_and_attempts(client, clean_mongo):
    """
    Deleting a document must take its generated study material with it.

    A quiz is generated from the document, submitted (so an attempt row exists),
    and then the document is deleted. The quiz and its attempts must disappear,
    while an unrelated quiz belonging to another document must survive.
    """
    from db.study_repositories import QuizAttemptRepository, QuizRepository

    _, token = register_user(client)
    headers = auth_headers(token)
    # Definition-shaped sentences so the deterministic (no-LLM) quiz generator
    # has real material to build questions from.
    study_text = (
        "Normalization is the process of organizing data to reduce redundancy "
        "in a relational database. "
        "A functional dependency is a relationship between two attributes where "
        "one attribute determines the other. "
        "BCNF is a normal form where every determinant is a candidate key of the relation. "
        "Decomposition is the process of breaking a relation into two or more relations. "
        "An anomaly is a problem that happens when data is not properly normalized. "
    )

    # --- document A + a quiz generated from it -------------------------
    document_a = _upload_text(client, token, text=study_text, filename="quiz-source-a.txt")
    quiz_response = client.post(
        "/api/study/quizzes/generate",
        json={"document_ids": [document_a["id"]], "counts": {"mcq": 2, "true_false": 1}},
        headers=headers,
    )
    assert quiz_response.status_code == 201, quiz_response.get_data(as_text=True)
    quiz_a_id = quiz_response.get_json()["data"]["id"]

    # The generate response is a summary; fetch the full quiz to get question ids.
    loaded = client.get(f"/api/study/quizzes/{quiz_a_id}", headers=headers)
    assert loaded.status_code == 200, loaded.get_data(as_text=True)
    quiz_a = loaded.get_json()["data"]
    assert quiz_a.get("questions"), (
        "the sample text must yield questions: " + loaded.get_data(as_text=True)
    )

    # Submit an attempt so there is a quiz_attempts row to cascade.
    answers = {
        question["question_id"]: "unknown"
        for question in quiz_a.get("questions", [])
    }
    submit = client.post(
        f"/api/study/quizzes/{quiz_a_id}/submit", json={"answers": answers}, headers=headers
    )
    assert submit.status_code in (200, 201), submit.get_data(as_text=True)
    user_id = _user_id(client, headers)
    assert QuizAttemptRepository().list_for_quiz(quiz_a_id, user_id), (
        "the submit must have stored an attempt"
    )

    # --- document B + its own quiz (must survive A's deletion) ---------
    document_b = _upload_text(client, token, text=study_text, filename="quiz-source-b.txt")
    quiz_b_response = client.post(
        "/api/study/quizzes/generate",
        json={"document_ids": [document_b["id"]], "counts": {"mcq": 2}},
        headers=headers,
    )
    assert quiz_b_response.status_code == 201, quiz_b_response.get_data(as_text=True)
    quiz_b_id = quiz_b_response.get_json()["data"]["id"]

    # --- delete document A --------------------------------------------
    deleted = client.delete(f"/api/documents/{document_a['id']}", headers=headers)
    assert deleted.status_code == 200, deleted.get_data(as_text=True)
    removed = deleted.get_json()["data"]["removed"]
    assert removed["quizzes"] >= 1, "document A's quiz must be reported as removed"

    remaining_ids = {
        str(row["_id"])
        for row in QuizRepository().collection.find({"user_id": user_id}, {"_id": 1})
    }
    assert quiz_a_id not in remaining_ids, "document A's quiz must be deleted"
    assert quiz_b_id in remaining_ids, "document B's quiz must survive"
    assert QuizAttemptRepository().list_for_quiz(quiz_a_id, user_id) == [], (
        "attempts of the deleted quiz must be removed too"
    )


def _user_id(client, headers):
    """Resolve the signed-in user's id from the API."""
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.get_data(as_text=True)
    payload = me.get_json()["data"]
    return (payload.get("user") or payload)["id"]


def test_reprocess_after_failure(client, clean_mongo, monkeypatch):
    """A failed document can be re-queued once the cause is fixed (brief §22)."""
    import services.pipeline as pipeline_module

    _, token = register_user(client)

    # Force the embedding stage to fail once.
    original = pipeline_module.DocumentPipeline._stage_index

    def fail_once(self, document, chunks, source_type):  # noqa: ARG002
        pipeline_module.DocumentPipeline._stage_index = original
        raise Exception("simulated embedding outage")

    monkeypatch.setattr(pipeline_module.DocumentPipeline, "_stage_index", fail_once)
    fail_upload = upload(client, token, text_upload(SAMPLE_TEXT, "flaky.txt"))
    assert fail_upload.get_json()["data"]["processing_status"] == "failed"

    monkeypatch.setattr(pipeline_module.DocumentPipeline, "_stage_index", original)
    document_id = fail_upload.get_json()["data"]["id"]
    response = client.post(f"/api/documents/{document_id}/reprocess",
                           headers=auth_headers(token))
    assert response.status_code == 200
    assert response.get_json()["data"]["processing_status"] == "completed"


def test_scanned_pdf_helper_produces_no_text():
    """Guard for the fixture itself: PyMuPDF must see nothing to extract."""
    import fitz

    document = fitz.open(stream=make_scanned_pdf_bytes(), filetype="pdf")
    try:
        combined = "".join(page.get_text("text", sort=True) for page in document)
    finally:
        document.close()
    assert combined.strip() == "", f"fixture leaks digital text: {combined!r}"
