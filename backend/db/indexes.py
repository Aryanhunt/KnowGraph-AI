"""
Index creation.

Called once from the app factory. Indexes make the per-user document queries,
duplicate detection, graph lookups and analytics aggregations fast, and enforce
the uniqueness guarantees the application relies on (one user per email, one
concept per user+slug, ...).
"""

from __future__ import annotations

import logging

from typing import Dict, Optional

from pymongo import ASCENDING, DESCENDING, TEXT
from pymongo.database import Database

from db.mongo import COLLECTIONS

logger = logging.getLogger(__name__)


def ensure_text_index(collection, keys, *, name: str, weights: Optional[Dict[str, int]] = None) -> None:
    """
    Create (or repair) a text index that never inspects the app's `language` field.

    ``default_language="none"`` disables stemming/stop-words so search behaves the
    same way the application's own normalisation does, and ``language_override``
    points at a field that does not exist. An existing index created with the old
    options is dropped first, because MongoDB cannot recreate an index with
    different options.
    """
    desired_override = "_text_language"
    try:
        existing = {index["name"]: index for index in collection.list_indexes()}
    except Exception:  # noqa: BLE001 - a fresh/unreachable collection has no indexes
        existing = {}

    current = existing.get(name)
    if current is not None and current.get("language_override", "language") != desired_override:
        logger.info("Recreating text index %s with explicit language override", name)
        collection.drop_index(name)

    try:
        collection.create_index(
            keys,
            name=name,
            default_language="none",
            language_override=desired_override,
            weights=weights or {},
        )
    except Exception as exc:  # noqa: BLE001 - keep boot resilient, but say why
        logger.warning("Could not create text index %s: %s", name, exc)


def ensure_indexes(database: Database) -> None:
    """Create every index KnowGraph AI needs. Idempotent."""
    # --- users ------------------------------------------------------------
    database[COLLECTIONS["users"]].create_index("email", unique=True, name="uniq_email")
    database[COLLECTIONS["users"]].create_index("created_at", name="created_at_idx")

    # --- documents --------------------------------------------------------
    documents = database[COLLECTIONS["documents"]]
    documents.create_index([("user_id", ASCENDING), ("upload_date", DESCENDING)], name="user_date_idx")
    documents.create_index([("user_id", ASCENDING), ("processing_status", ASCENDING)], name="user_status_idx")
    documents.create_index([("user_id", ASCENDING), ("file_hash", ASCENDING)], name="user_hash_idx")
    documents.create_index([("user_id", ASCENDING), ("subject", ASCENDING)], name="user_subject_idx")
    documents.create_index("tags", name="tags_idx")
    # Full-text index powers the keyword half of hybrid search.
    # NOTE: `language_override` must NOT be the app's `language` field, otherwise
    # MongoDB parses values like "unknown" as a language name and rejects writes.
    ensure_text_index(
        documents,
        [("title", TEXT), ("summary", TEXT), ("tags", TEXT), ("topics", TEXT)],
        name="document_text_idx",
    )

    # --- pages ------------------------------------------------------------
    pages = database[COLLECTIONS["document_pages"]]
    pages.create_index([("document_id", ASCENDING), ("page_number", ASCENDING)], name="doc_page_idx")
    pages.create_index("user_id", name="page_user_idx")

    # --- chunks -----------------------------------------------------------
    chunks = database[COLLECTIONS["document_chunks"]]
    chunks.create_index([("document_id", ASCENDING), ("chunk_index", ASCENDING)], name="doc_chunk_idx")
    chunks.create_index("embedding_id", name="embedding_idx")
    # Keyword search inside chunk text (hybrid retrieval + search-by-page).
    ensure_text_index(
        chunks,
        [("text", TEXT), ("document_id", ASCENDING)],
        name="chunk_text_idx",
        weights={"text": 10},
    )

    # --- knowledge graph --------------------------------------------------
    concepts = database[COLLECTIONS["concepts"]]
    concepts.create_index([("user_id", ASCENDING), ("slug", ASCENDING)], unique=True, name="uniq_user_concept")
    concepts.create_index([("user_id", ASCENDING), ("label", ASCENDING)], name="user_label_idx")

    relations = database[COLLECTIONS["concept_relations"]]
    relations.create_index([("user_id", ASCENDING), ("source_slug", ASCENDING)], name="rel_source_idx")
    relations.create_index([("user_id", ASCENDING), ("target_slug", ASCENDING)], name="rel_target_idx")
    relations.create_index(
        [("user_id", ASCENDING), ("source_slug", ASCENDING), ("target_slug", ASCENDING), ("relation", ASCENDING)],
        unique=True,
        name="uniq_relation",
    )

    # --- study ------------------------------------------------------------
    flashcards = database[COLLECTIONS["flashcards"]]
    flashcards.create_index([("user_id", ASCENDING), ("document_id", ASCENDING)], name="card_user_doc_idx")
    flashcards.create_index([("user_id", ASCENDING), ("topic", ASCENDING)], name="card_topic_idx")

    quizzes = database[COLLECTIONS["quizzes"]]
    quizzes.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)], name="quiz_user_date_idx")

    attempts = database[COLLECTIONS["quiz_attempts"]]
    attempts.create_index([("user_id", ASCENDING), ("quiz_id", ASCENDING)], name="attempt_user_quiz_idx")
    attempts.create_index([("user_id", ASCENDING), ("submitted_at", DESCENDING)], name="attempt_user_date_idx")

    # --- chat -------------------------------------------------------------
    sessions = database[COLLECTIONS["chat_sessions"]]
    sessions.create_index([("user_id", ASCENDING), ("updated_at", DESCENDING)], name="session_user_date_idx")

    messages = database[COLLECTIONS["chat_messages"]]
    messages.create_index([("session_id", ASCENDING), ("created_at", ASCENDING)], name="message_session_idx")

    # --- analytics --------------------------------------------------------
    database[COLLECTIONS["search_logs"]].create_index(
        [("user_id", ASCENDING), ("created_at", DESCENDING)], name="search_user_date_idx"
    )
    events = database[COLLECTIONS["study_events"]]
    events.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)], name="event_user_date_idx")
    events.create_index([("user_id", ASCENDING), ("topic", ASCENDING)], name="event_topic_idx")

    logger.info("MongoDB indexes verified")