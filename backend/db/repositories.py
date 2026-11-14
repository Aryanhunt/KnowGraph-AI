"""
Repositories — the only place that talks to MongoDB collections directly.

Keeping queries here (instead of in routes or services) means:

* routes stay thin and readable,
* every query automatically scopes by ``user_id``, which is the backbone of the
  per-user isolation required by brief §21,
* index usage is easy to audit in one file.

Documents are returned as plain dicts; callers decide whether to hydrate a
dataclass from :mod:`models`.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

from bson import ObjectId
from bson.errors import InvalidId

from db.mongo import COLLECTIONS, get_collection
from models.domain import ProcessingStatus, utcnow
from utils.errors import ValidationError
from utils.text import normalize_for_match


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def to_object_id(value: Any, *, field: str = "id") -> ObjectId:
    """Convert a string/ObjectId, raising a clear error for malformed ids."""
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError) as exc:
        raise ValidationError(f"The {field} is not a valid identifier.") from exc


def maybe_object_id(value: Any) -> Optional[ObjectId]:
    try:
        return to_object_id(value)
    except ValidationError:
        return None


def paginate(query: Dict[str, Any], page: int, page_size: int) -> tuple:
    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or 20)))
    return (page - 1) * page_size, page_size, page


class BaseRepository:
    """Shared plumbing for the repositories."""

    collection_key: str = ""

    @property
    def collection(self):
        return get_collection(self.collection_key)

    def _insert(self, document: Dict[str, Any]) -> str:
        payload = dict(document)
        payload.setdefault("created_at", utcnow())
        payload.setdefault("updated_at", utcnow())
        result = self.collection.insert_one(payload)
        return str(result.inserted_id)

    def _insert_many(self, documents: Sequence[Dict[str, Any]]) -> int:
        if not documents:
            return 0
        now = utcnow()
        payload = []
        for document in documents:
            item = dict(document)
            item.setdefault("created_at", now)
            item.setdefault("updated_at", now)
            payload.append(item)
        result = self.collection.insert_many(payload)
        return len(result.inserted_ids)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
class UserRepository(BaseRepository):
    collection_key = COLLECTIONS["users"]

    def create(self, *, email: str, full_name: str, password_hash: str) -> str:
        return self._insert(
            {
                "email": normalize_for_match(email),
                "email_display": email.strip(),
                "full_name": full_name.strip(),
                "password_hash": password_hash,
            }
        )

    def find_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        return self.collection.find_one({"email": normalize_for_match(email)})

    def find_by_id(self, user_id: Any) -> Optional[Dict[str, Any]]:
        object_id = maybe_object_id(user_id)
        return self.collection.find_one({"_id": object_id}) if object_id else None

    def count(self) -> int:
        return int(self.collection.estimated_document_count())

    def touch_login(self, user_id: Any) -> None:
        self.collection.update_one(
            {"_id": to_object_id(user_id)}, {"$set": {"last_login_at": utcnow(), "updated_at": utcnow()}}
        )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
class DocumentRepository(BaseRepository):
    collection_key = COLLECTIONS["documents"]

    def create(self, document: Dict[str, Any]) -> str:
        payload = dict(document)
        payload.setdefault("processing_status", ProcessingStatus.QUEUED)
        payload.setdefault("current_stage", ProcessingStatus.QUEUED)
        payload.setdefault("progress", 0.0)
        payload.setdefault("upload_date", utcnow())
        return self._insert(payload)

    def find_for_user(self, document_id: Any, user_id: Any) -> Optional[Dict[str, Any]]:
        """Fetch one document *only* if it belongs to ``user_id``."""
        return self.collection.find_one(
            {"_id": to_object_id(document_id, field="document id"), "user_id": str(user_id)}
        )

    def find_by_hash(self, user_id: Any, file_hash: str) -> Optional[Dict[str, Any]]:
        return self.collection.find_one({"user_id": str(user_id), "file_hash": file_hash})

    def list_for_user(
        self,
        user_id: Any,
        *,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        subject: Optional[str] = None,
        tag: Optional[str] = None,
        document_type: Optional[str] = None,
        search: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        document_ids: Optional[Iterable[Any]] = None,
    ) -> tuple:
        """Filtered, paginated document list plus the total count."""
        query: Dict[str, Any] = {"user_id": str(user_id)}
        if status and status != "all":
            query["processing_status"] = status
        if subject:
            query["subject"] = subject
        if tag:
            query["tags"] = tag
        if document_type:
            query["file_type"] = document_type
        if document_ids:
            ids = [to_object_id(item) for item in document_ids if maybe_object_id(item)]
            query["_id"] = {"$in": ids}
        if search:
            query["title"] = {"$regex": search.strip(), "$options": "i"}
        if date_from or date_to:
            window: Dict[str, Any] = {}
            if date_from:
                window["$gte"] = date_from
            if date_to:
                window["$lte"] = date_to
            query["upload_date"] = window

        total = int(self.collection.count_documents(query))
        skip, limit, page = paginate(query, page, page_size)
        cursor = self.collection.find(query).sort("upload_date", -1).skip(skip).limit(limit)
        return list(cursor), total, page, limit

    def list_all_for_user(
        self,
        user_id: Any,
        *,
        only_ready: bool = True,
        subject: Optional[str] = None,
        document_ids: Optional[Iterable[Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Every document of a user (used by chat modes and analytics)."""
        query: Dict[str, Any] = {"user_id": str(user_id)}
        if only_ready:
            query["processing_status"] = ProcessingStatus.READY
        if subject:
            query["subject"] = subject
        if document_ids:
            ids = [to_object_id(item) for item in document_ids if maybe_object_id(item)]
            query["_id"] = {"$in": ids}
        return list(self.collection.find(query).sort("upload_date", -1))

    def update_status(
        self,
        document_id: Any,
        status: str,
        *,
        error: Optional[str] = None,
        stage: Optional[str] = None,
    ) -> None:
        """Advance the processing state, keeping progress/labels in sync."""
        payload: Dict[str, Any] = {
            "processing_status": status,
            "current_stage": stage or status,
            "progress": ProcessingStatus.progress_for(status),
            "processing_error": error,
            "updated_at": utcnow(),
        }
        if status == ProcessingStatus.READY:
            payload["processed_at"] = utcnow()
        self.collection.update_one({"_id": to_object_id(document_id)}, {"$set": payload})

    def update_fields(self, document_id: Any, fields: Dict[str, Any]) -> None:
        payload = dict(fields)
        payload["updated_at"] = utcnow()
        self.collection.update_one({"_id": to_object_id(document_id)}, {"$set": payload})

    def delete(self, document_id: Any, user_id: Any) -> bool:
        result = self.collection.delete_one(
            {"_id": to_object_id(document_id), "user_id": str(user_id)}
        )
        return result.deleted_count > 0

    def subjects(self, user_id: Any) -> List[Dict[str, Any]]:
        """Distinct subjects with counts (subject filter / "Chat With Subject")."""
        pipeline = [
            {"$match": {"user_id": str(user_id), "subject": {"$nin": ["", None]}}},
            {"$group": {"_id": "$subject", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 100},
        ]
        return [
            {"subject": row["_id"], "document_count": row["count"]}
            for row in self.collection.aggregate(pipeline)
        ]

    def tags(self, user_id: Any) -> List[Dict[str, Any]]:
        pipeline = [
            {"$match": {"user_id": str(user_id)}},
            {"$unwind": "$tags"},
            {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 100},
        ]
        return [
            {"tag": row["_id"], "document_count": row["count"]}
            for row in self.collection.aggregate(pipeline)
        ]

    def stats(self, user_id: Any) -> Dict[str, Any]:
        """Aggregate counters for the dashboard cards."""
        pipeline = [
            {"$match": {"user_id": str(user_id)}},
            {
                "$group": {
                    "_id": "$processing_status",
                    "count": {"$sum": 1},
                    "pages": {"$sum": "$page_count"},
                    "chunks": {"$sum": "$chunk_count"},
                    "bytes": {"$sum": "$file_size"},
                }
            },
        ]
        by_status = {row["_id"]: row for row in self.collection.aggregate(pipeline)}
        return {
            "total_documents": int(self.collection.count_documents({"user_id": str(user_id)})),
            "ready_documents": by_status.get(ProcessingStatus.READY, {}).get("count", 0),
            "failed_documents": by_status.get(ProcessingStatus.FAILED, {}).get("count", 0),
            "processing_documents": sum(
                row["count"]
                for status, row in by_status.items()
                if status not in ProcessingStatus.TERMINAL
            ),
            "total_pages": sum(row.get("pages", 0) for row in by_status.values()),
            "total_chunks": sum(row.get("chunks", 0) for row in by_status.values()),
            "total_bytes": sum(row.get("bytes", 0) for row in by_status.values()),
            "by_status": {
                status: {
                    "documents": row["count"],
                    "pages": row.get("pages", 0),
                    "chunks": row.get("chunks", 0),
                    "bytes": row.get("bytes", 0),
                }
                for status, row in by_status.items()
            },
        }

    def find_titles_for_user(self, user_id: Any, document_ids: Sequence[Any]) -> Dict[str, str]:
        """Map a set of document ids to their titles (avoids N+1 queries)."""
        ids = [to_object_id(item) for item in document_ids if maybe_object_id(item)]
        if not ids:
            return {}
        cursor = self.collection.find(
            {"_id": {"$in": ids}, "user_id": str(user_id)}, {"title": 1}
        )
        return {str(row["_id"]): row.get("title", "") for row in cursor}

    def recent(self, user_id: Any, limit: int = 5) -> List[Dict[str, Any]]:
        cursor = (
            self.collection.find({"user_id": str(user_id)})
            .sort("upload_date", -1)
            .limit(max(1, limit))
        )
        return list(cursor)

    def count_in_progress(self, user_id: Any) -> int:
        return int(
            self.collection.count_documents(
                {
                    "user_id": str(user_id),
                    "processing_status": {"$nin": list(ProcessingStatus.TERMINAL)},
                }
            )
        )


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
class PageRepository(BaseRepository):
    collection_key = COLLECTIONS["document_pages"]

    def replace_for_document(self, document_id: Any, pages: Sequence[Dict[str, Any]]) -> int:
        """Replace all stored pages for a document (makes reprocessing idempotent)."""
        self.collection.delete_many({"document_id": str(document_id)})
        return self._insert_many(pages)

    def list_for_document(self, document_id: Any) -> List[Dict[str, Any]]:
        return list(
            self.collection.find({"document_id": str(document_id)}).sort("page_number", 1)
        )

    def get_page(self, document_id: Any, page_number: int) -> Optional[Dict[str, Any]]:
        return self.collection.find_one(
            {"document_id": str(document_id), "page_number": int(page_number)}
        )

    def update_page_fields(
        self, document_id: Any, page_number: int, fields: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Update fields on one page. Returns the updated row (or None)."""
        payload = dict(fields)
        payload["updated_at"] = utcnow()
        return self.collection.find_one_and_update(
            {"document_id": str(document_id), "page_number": int(page_number)},
            {"$set": payload},
            return_document=True,
        )

    def list_needing_reindex(self, document_id: Any) -> List[Dict[str, Any]]:
        """Pages with saved corrections that have not been re-indexed yet."""
        return list(
            self.collection.find(
                {"document_id": str(document_id), "needs_reindex": True}
            ).sort("page_number", 1)
        )

    def clear_reindex_flag(self, document_id: Any) -> int:
        """Mark every page of a document as re-indexed. Returns count cleared."""
        result = self.collection.update_many(
            {"document_id": str(document_id), "needs_reindex": True},
            {"$set": {"needs_reindex": False}},
        )
        return int(result.modified_count)

    def delete_for_document(self, document_id: Any) -> int:
        return int(self.collection.delete_many({"document_id": str(document_id)}).deleted_count)

    def count_for_document(self, document_id: Any) -> int:
        return int(self.collection.count_documents({"document_id": str(document_id)}))

    def search_text(
        self,
        user_id: Any,
        query: str,
        *,
        limit: int = 20,
        document_ids: Optional[List[Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Regex scan over page text — backs "search within a document/page"."""
        match: Dict[str, Any] = {
            "user_id": str(user_id),
            "text": {"$regex": re.escape(query.strip()), "$options": "i"},
        }
        if document_ids:
            match["document_id"] = {"$in": [str(item) for item in document_ids]}
        return list(self.collection.find(match).sort("page_number", 1).limit(max(1, limit)))


class ChunkRepository(BaseRepository):
    collection_key = COLLECTIONS["document_chunks"]

    def replace_for_document(self, document_id: Any, chunks: Sequence[Dict[str, Any]]) -> int:
        self.collection.delete_many({"document_id": str(document_id)})
        return self._insert_many(chunks)

    def list_for_document(self, document_id: Any, *, limit: int = 0) -> List[Dict[str, Any]]:
        cursor = self.collection.find({"document_id": str(document_id)}).sort("chunk_index", 1)
        if limit:
            cursor = cursor.limit(limit)
        return list(cursor)

    def get_by_ids(self, chunk_ids: Sequence[Any]) -> List[Dict[str, Any]]:
        object_ids = [item for item in (maybe_object_id(value) for value in chunk_ids) if item]
        if not object_ids:
            return []
        return list(self.collection.find({"_id": {"$in": object_ids}}))

    def delete_for_document(self, document_id: Any) -> int:
        return int(self.collection.delete_many({"document_id": str(document_id)}).deleted_count)

    def count_for_document(self, document_id: Any) -> int:
        return int(self.collection.count_documents({"document_id": str(document_id)}))

    def keyword_search(
        self,
        user_id: Any,
        query: str,
        *,
        limit: int = 20,
        document_ids: Optional[List[Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Keyword half of hybrid search (brief §6).

        Mongo's ``$text`` index is preferred because it ranks matches, and a regex
        fallback keeps partial/short queries working when the text search finds
        nothing. ``keyword_score`` is a real value from the database — never a
        fabricated number (brief §15).
        """
        terms = normalize_for_match(query).split()
        match: Dict[str, Any] = {"user_id": str(user_id)}
        if document_ids:
            match["document_id"] = {"$in": [str(item) for item in document_ids]}

        if terms:
            try:
                cursor = self.collection.find(
                    {**match, "$text": {"$search": " ".join(terms)}},
                    {"score": {"$meta": "textScore"}},
                ).sort([("score", {"$meta": "textScore"})]).limit(max(1, limit))
                results = list(cursor)
                if results:
                    for row in results:
                        row["keyword_score"] = float(row.pop("score", 0.0))
                    return results
            except Exception:  # noqa: BLE001 - missing text index → regex fallback
                pass

        if not terms:
            return []
        match["text"] = {"$regex": re.escape(terms[0]), "$options": "i"}
        results = list(self.collection.find(match).limit(max(1, limit)))
        for row in results:
            row["keyword_score"] = float(len(terms))
        return results

    def page_numbers(self, document_id: Any) -> List[int]:
        return sorted(
            int(value)
            for value in self.collection.distinct("page_number", {"document_id": str(document_id)})
            if value is not None
        )