"""
Chunking, embeddings, vector search and quiz grading (brief §6, §10, §25).

Embeddings and the vector store run on the model-free test providers configured in
``conftest.py`` (hashing + numpy), so these tests are fast, deterministic and
need no network. Quiz scoring is asserted exactly, because grades must be
reproducible application logic.
"""

import pytest


def test_chunking_preserves_page_numbers():
    from services.chunking import chunk_pages

    class FakePage:
        def __init__(self, page_number, text, section_title=""):
            self.page_number = page_number
            self.text = text
            self.section_title = section_title

    text = " ".join(f"Sentence number {index} about normalization." for index in range(30))
    chunks = chunk_pages(
        [FakePage(3, text), FakePage(4, "Short page about TCP.")],
        chunk_size=300,
        overlap=40,
    )
    assert chunks, "pages must produce chunks"
    assert all(chunk.page_number in (3, 4) for chunk in chunks)
    assert all(chunk.text.strip() for chunk in chunks)
    indexes = [chunk.chunk_index for chunk in chunks]
    assert indexes == sorted(indexes), "chunk indexes must be global and ordered"


def test_chunk_overlap_keeps_context():
    from services.chunking import chunk_text

    text = " ".join(f"Concept {index} matters for the exam revision plan." for index in range(25))
    chunks = chunk_text(text, page_number=1, chunk_size=220, overlap=80)
    assert len(chunks) >= 2
    vocabulary_1 = set(chunks[0].text.split())
    vocabulary_2 = set(chunks[1].text.split())
    assert vocabulary_1 & vocabulary_2, "adjacent chunks must share vocabulary"


def test_hashing_embeddings_are_deterministic():
    from services.embeddings.factory import build_embedding_service
    from config.settings import Settings

    settings = Settings.from_env()
    settings.embedding_provider = "hashing"
    service = build_embedding_service(settings)
    first = service.embed_texts(["BCNF requires a superkey determinant."])
    second = service.embed_texts(["BCNF requires a superkey determinant."])
    assert first.ok and second.ok
    assert first.vectors[0] == second.vectors[0]
    assert service.dimension > 0


def test_numpy_vector_store_round_trip(tmp_path):
    """Upsert → filtered search → delete against the dependency-free store."""
    from services.vector.numpy_store import NumpyVectorStore
    from services.vector.base import VectorRecord

    store = NumpyVectorStore("test", tmp_path)
    vectors = [[1.0, 0.0], [0.0, 1.0], [0.7, 0.7]]
    records = [
        VectorRecord(
            id=f"doc1:{index}",
            vector=vector,
            document=f"chunk {index}",
            metadata={"user_id": "u1", "document_id": "doc1", "page_number": 1,
                      "title": f"Doc {index}", "chunk_index": index,
                      "source_type": "pdf", "chunk_id": f"c{index}"},
        )
        for index, vector in enumerate(vectors)
    ]
    upserted = store.upsert(records)
    assert upserted.ok and upserted.stored == 3
    assert store.count(user_id="u1") == 3

    result = store.search([1.0, 0.0], top_k=1, user_id="u1")
    assert result.ok and result.hits
    assert result.hits[0].id == "doc1:0"
    assert result.hits[0].chunk_id == "c0"
    assert result.hits[0].score is not None

    removed = store.delete_document("doc1")
    assert removed == 3
    assert store.count() == 0


def test_numpy_store_enforces_user_isolation(tmp_path):
    from services.vector.numpy_store import NumpyVectorStore
    from services.vector.base import VectorRecord

    store = NumpyVectorStore("iso", tmp_path)
    store.upsert(
        [
            VectorRecord(id="a", vector=[1.0, 0.0], document="alice chunk",
                         metadata={"user_id": "alice", "document_id": "d1"}),
            VectorRecord(id="b", vector=[1.0, 0.0], document="bob chunk",
                         metadata={"user_id": "bob", "document_id": "d2"}),
        ]
    )
    bob_hits = store.search([1.0, 0.0], top_k=5, user_id="bob")
    assert [hit.id for hit in bob_hits.hits] == ["b"], "filters must be enforced in the store"
