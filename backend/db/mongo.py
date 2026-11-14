"""
MongoDB connection management (metadata store only).

Files themselves live on disk (``backend/storage``); MongoDB holds the
documents, pages, chunks, graph, study and analytics metadata described in
brief §5.

The connection is created lazily so importing the app never fails when MongoDB
is not running yet, and every failure is surfaced as a friendly
``database_unavailable`` error instead of a stack trace (brief §22).
"""

from __future__ import annotations

import logging
from typing import Optional

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

from config.settings import Settings
from utils.errors import database_unavailable, DatabaseError

logger = logging.getLogger(__name__)

# Collection names in one place so routes/services never hard-code strings.
COLLECTIONS = {
    "users": "users",
    "documents": "documents",
    "document_pages": "document_pages",
    "document_chunks": "document_chunks",
    "concepts": "concepts",
    "concept_relations": "concept_relations",
    "flashcards": "flashcards",
    "quizzes": "quizzes",
    "quiz_attempts": "quiz_attempts",
    "chat_sessions": "chat_sessions",
    "chat_messages": "chat_messages",
    "search_logs": "search_logs",
    "study_events": "study_events",
}


class MongoManager:
    """Thin wrapper around :class:`pymongo.MongoClient`."""

    def __init__(self, uri: str, db_name: str, *, timeout_ms: int = 4000) -> None:
        self.uri = uri
        self.db_name = db_name
        self._client: Optional[MongoClient] = None
        self._database: Optional[Database] = None
        # Short timeout keeps the API responsive when MongoDB is simply not up.
        self._client_kwargs = {
            "serverSelectionTimeoutMS": timeout_ms,
            "connectTimeoutMS": timeout_ms,
            "appname": "knowgraph-ai",
        }

    # -- lifecycle ---------------------------------------------------------
    def connect(self) -> Database:
        if self._database is not None:
            return self._database
        try:
            self._client = MongoClient(self.uri, **self._client_kwargs)
            self._database = self._client[self.db_name]
            # Fail fast here rather than on the first query.
            self._client.admin.command("ping")
            logger.info("Connected to MongoDB at %s (db=%s)", self.uri, self.db_name)
            return self._database
        except (ServerSelectionTimeoutError, PyMongoError) as exc:
            self.close()
            raise database_unavailable(str(exc)) from exc
        except Exception as exc:  # pragma: no cover - unexpected driver error
            self.close()
            raise database_unavailable(str(exc)) from exc

    def ping(self) -> bool:
        try:
            if self._client is None:
                self.connect()
            assert self._client is not None
            self._client.admin.command("ping")
            return True
        except (PyMongoError, DatabaseError):
            return False

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            finally:
                self._client = None
                self._database = None

    # -- access ------------------------------------------------------------
    @property
    def database(self) -> Database:
        return self.connect() if self._database is None else self._database

    def collection(self, key_or_name: str):
        """Fetch a collection by logical key (see :data:`COLLECTIONS`) or raw name."""
        return self.database[COLLECTIONS.get(key_or_name, key_or_name)]


_manager: Optional[MongoManager] = None


def init_mongo(settings: Settings) -> MongoManager:
    """Create (or replace) the process-wide MongoDB manager."""
    global _manager
    _manager = MongoManager(settings.mongo_uri, settings.mongo_db_name)
    return _manager


def get_mongo() -> MongoManager:
    if _manager is None:
        # Imported lazily to avoid a circular import with config helpers.
        from config.settings import settings as current

        init_mongo(current)
    assert _manager is not None
    return _manager


def get_db() -> Database:
    return get_mongo().database


def get_collection(key_or_name: str):
    return get_mongo().collection(key_or_name)


def reset_mongo() -> None:
    """Drop the cached connection (used by tests and by --reload restarts)."""
    global _manager
    if _manager is not None:
        _manager.close()
    _manager = None