"""
Repositories for the knowledge graph, study features, chat and analytics.

Same rules as ``db/repositories.py``: every query is scoped by ``user_id``, and
anything a user can see passes through one of these methods.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from db.mongo import COLLECTIONS, get_collection
from db.repositories import BaseRepository, paginate, to_object_id
from models.domain import utcnow
from utils.text import normalize_for_match, slugify


# ---------------------------------------------------------------------------
# Knowledge graph — concepts
# ---------------------------------------------------------------------------
class ConceptRepository(BaseRepository):
    collection_key = COLLECTIONS["concepts"]

    def upsert(
        self,
        *,
        user_id: Any,
        label: str,
        document_id: str,
        document_title: str,
        page_numbers: Sequence[int],
        occurrences: int,
        score: float,
        definition: str = "",
        snippets: Optional[Sequence[str]] = None,
    ) -> str:
        """
        Merge a concept into the user's graph.

        Concepts are shared across a user's documents: uploading a second DBMS note
        containing the same concept adds to ``document_ids``/``page_refs`` instead
        of creating a duplicate node (brief §9).
        """
        slug = slugify(label)
        snippet_list = list(snippets or [])
        page_refs = [
            {
                "document_id": str(document_id),
                "document_title": document_title,
                "page_number": int(page),
                "snippet": snippet_list[index] if index < len(snippet_list) else "",
            }
            for index, page in enumerate(page_numbers)
        ]
        self.collection.update_one(
            {"user_id": str(user_id), "slug": slug},
            {
                "$set": {
                    "label": label,
                    "normalized": normalize_for_match(label),
                    "definition": definition,
                    "updated_at": utcnow(),
                },
                "$inc": {"occurrences": int(occurrences)},
                "$max": {"score": float(score)},
                "$addToSet": {"document_ids": str(document_id)},
                "$push": {"page_refs": {"$each": page_refs}},
            },
            upsert=True,
        )
        # `document_count` is the size of the *distinct* document set, not a counter:
        # incrementing it made a concept seen in one reprocessed document claim two.
        stored = self.collection.find_one(
            {"user_id": str(user_id), "slug": slug}, {"document_ids": 1}
        )
        self.collection.update_one(
            {"user_id": str(user_id), "slug": slug},
            {"$set": {"document_count": len((stored or {}).get("document_ids", []) or [])}},
        )
        return slug

    def list_for_user(
        self,
        user_id: Any,
        *,
        search: Optional[str] = None,
        document_ids: Optional[List[Any]] = None,
        limit: int = 200,
        min_score: float = 0.0,
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"user_id": str(user_id), "score": {"$gte": float(min_score)}}
        if search:
            query["normalized"] = {"$regex": normalize_for_match(search), "$options": "i"}
        if document_ids:
            query["document_ids"] = {"$in": [str(item) for item in document_ids]}
        cursor = (
            self.collection.find(query)
            .sort([("score", -1), ("occurrences", -1)])
            .limit(max(1, limit))
        )
        return list(cursor)

    def find_by_slug(self, user_id: Any, slug: str) -> Optional[Dict[str, Any]]:
        return self.collection.find_one({"user_id": str(user_id), "slug": slug})

    def labels(self, user_id: Any, *, limit: int = 200) -> List[str]:
        return [
            str(row["label"])
            for row in self.collection.find({"user_id": str(user_id)}, {"label": 1})
            .sort([("score", -1)])
            .limit(max(1, limit))
        ]

    def remove_document(self, user_id: Any, document_id: str) -> Dict[str, int]:
        """
        Detach a document from every concept.

        Concepts seen *only* in the deleted document disappear; surviving concepts
        are trimmed back to their remaining page references, so the graph never
        points at a document that no longer exists.
        """
        target = str(document_id)
        touched = 0
        removed = 0
        for concept in self.collection.find({"user_id": str(user_id), "document_ids": target}):
            remaining_pages = [
                ref for ref in concept.get("page_refs", []) if str(ref.get("document_id")) != target
            ]
            remaining_docs = [
                str(item) for item in concept.get("document_ids", []) if str(item) != target
            ]
            if not remaining_docs or not remaining_pages:
                self.collection.delete_one({"_id": concept["_id"]})
                removed += 1
                continue
            self.collection.update_one(
                {"_id": concept["_id"]},
                {
                    "$set": {
                        "page_refs": remaining_pages,
                        "document_ids": remaining_docs,
                        "document_count": len(remaining_docs),
                        "occurrences": len(remaining_pages),
                        "updated_at": utcnow(),
                    }
                },
            )
            touched += 1
        return {"updated": touched, "deleted": removed}

    def count(self, user_id: Any) -> int:
        return int(self.collection.count_documents({"user_id": str(user_id)}))


# ---------------------------------------------------------------------------
# Knowledge graph — relations
# ---------------------------------------------------------------------------
class RelationRepository(BaseRepository):
    collection_key = COLLECTIONS["concept_relations"]

    def upsert(
        self,
        *,
        user_id: Any,
        source_slug: str,
        target_slug: str,
        relation: str,
        method: str,
        weight: float = 1.0,
        evidence: Optional[Dict[str, Any]] = None,
        confidence: Optional[float] = None,
        verification_status: Optional[str] = None,
    ) -> None:
        """Insert or strengthen one typed edge (unique per user + pair + type)."""
        from models.graph import (
            default_relation_confidence,
            relations_contradict,
            verification_for_method,
        )

        # --- validation -----------------------------------------------------
        source_slug = str(source_slug or "").strip().lower()
        target_slug = str(target_slug or "").strip().lower()
        if not source_slug or not target_slug or source_slug == target_slug:
            return  # self-loops and empty ids are never stored
        relation = str(relation or "related_to").strip().lower()
        method = str(method or "cooccurrence").strip().lower()

        # A contradictory type on the same ordered pair is refused: the stored
        # (heavier/older) edge keeps its meaning instead of being overwritten.
        existing = list(
            self.collection.find(
                {
                    "user_id": str(user_id),
                    "source_slug": source_slug,
                    "target_slug": target_slug,
                }
            )
        )
        for row in existing:
            if relations_contradict(relation, str(row.get("relation", ""))):
                return

        evidence = dict(evidence or {})
        evidence_count = 1
        if confidence is None:
            confidence = default_relation_confidence(method, [evidence])
        verification_status = verification_status or verification_for_method(method)

        update: Dict[str, Any] = {
            "$set": {
                "relation": relation,
                "method": method,
                "confidence": round(float(confidence), 2),
                "verification_status": verification_status,
                "evidence_count": evidence_count,
                "updated_at": utcnow(),
            },
            "$inc": {"weight": float(weight)},
            "$setOnInsert": {"created_at": utcnow()},
        }
        if evidence:
            update["$addToSet"] = {"evidence": evidence}
        self.collection.update_one(
            {
                "user_id": str(user_id),
                "source_slug": source_slug,
                "target_slug": target_slug,
                "relation": relation,
            },
            update,
            upsert=True,
        )

    def list_for_user(
        self,
        user_id: Any,
        *,
        slugs: Optional[Sequence[str]] = None,
        relation: Optional[str] = None,
        verification: Optional[str] = None,
        min_confidence: Optional[float] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"user_id": str(user_id)}
        if slugs:
            wanted = list(slugs)
            query["$or"] = [{"source_slug": {"$in": wanted}}, {"target_slug": {"$in": wanted}}]
        if relation:
            query["relation"] = relation
        if verification:
            query["verification_status"] = verification
        if min_confidence is not None:
            threshold = float(min_confidence)
            if threshold > 0:
                # Only filter on a positive threshold. When the caller passes 0
                # (e.g. verification="all"), we omit the field entirely so that
                # edges written by older code with a null/missing confidence
                # field are still returned — in MongoDB {"$gte": 0.0} silently
                # excludes null/missing values, which previously hid every edge
                # that lacked an explicit confidence score.
                query["confidence"] = {"$gte": threshold}
        return list(self.collection.find(query).sort("weight", -1).limit(max(1, limit)))

    def update_verification(
        self,
        user_id: Any,
        source_slug: str,
        target_slug: str,
        relation: str,
        verification_status: str,
    ) -> bool:
        """Accept/reject a stored edge without deleting it (hidden vs shown)."""
        result = self.collection.update_one(
            {
                "user_id": str(user_id),
                "source_slug": str(source_slug or "").strip().lower(),
                "target_slug": str(target_slug or "").strip().lower(),
                "relation": str(relation or "related_to").strip().lower(),
            },
            {
                "$set": {
                    "verification_status": verification_status,
                    "updated_at": utcnow(),
                }
            },
        )
        return bool(result.matched_count)

    def neighbors(self, user_id: Any, slug: str, limit: int = 20) -> List[Dict[str, Any]]:
        cursor = (
            self.collection.find(
                {"user_id": str(user_id), "$or": [{"source_slug": slug}, {"target_slug": slug}]}
            )
            .sort("weight", -1)
            .limit(max(1, limit))
        )
        return list(cursor)

    def prerequisites(self, user_id: Any, slug: str, limit: int = 12) -> List[Dict[str, Any]]:
        """"Study X before this concept" edges (learning path, brief §12)."""
        cursor = (
            self.collection.find(
                {
                    "user_id": str(user_id),
                    "target_slug": slug,
                    "relation": {"$in": ["prerequisite_of", "requires", "part_of"]},
                }
            )
            .sort("weight", -1)
            .limit(max(1, limit))
        )
        return list(cursor)

    def remove_document(self, user_id: Any, document_id: str) -> int:
        """Delete edges that were evidenced *only* by the removed document."""
        target = str(document_id)
        removed = 0
        for relation in self.collection.find({"user_id": str(user_id)}):
            evidence = relation.get("evidence", [])
            remaining = [
                item for item in evidence if str(item.get("document_id")) != target
            ]
            if not remaining:
                self.collection.delete_one({"_id": relation["_id"]})
                removed += 1
            elif len(remaining) != len(evidence):
                self.collection.update_one(
                    {"_id": relation["_id"]},
                    {"$set": {"evidence": remaining, "updated_at": utcnow()}},
                )
        return removed

    def count(self, user_id: Any) -> int:
        return int(self.collection.count_documents({"user_id": str(user_id)}))

    def count_by_verification(self, user_id: Any, status: str) -> int:
        """How many edges carry a given verification status."""
        return int(
            self.collection.count_documents(
                {"user_id": str(user_id), "verification_status": str(status)}
            )
        )

    def delete_all_for_user(self, user_id: Any) -> int:
        return int(self.collection.delete_many({"user_id": str(user_id)}).deleted_count)


# ---------------------------------------------------------------------------
# Flashcards
# ---------------------------------------------------------------------------
class FlashcardRepository(BaseRepository):
    collection_key = COLLECTIONS["flashcards"]

    def create_many(self, cards: Sequence[Dict[str, Any]]) -> int:
        return self._insert_many(cards)

    def list_for_user(
        self,
        user_id: Any,
        *,
        document_ids: Optional[List[Any]] = None,
        topic: Optional[str] = None,
        review_status: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple:
        query: Dict[str, Any] = {"user_id": str(user_id)}
        if document_ids:
            query["document_ids"] = {"$in": [str(item) for item in document_ids]}
        if topic:
            query["topic"] = topic
        if review_status:
            query["review_status"] = review_status

        total = int(self.collection.count_documents(query))
        skip, limit, page = paginate(query, page, page_size)
        cursor = self.collection.find(query).sort("created_at", -1).skip(skip).limit(limit)
        return list(cursor), total, page, limit

    def get(self, card_id: Any, user_id: Any) -> Optional[Dict[str, Any]]:
        return self.collection.find_one(
            {"_id": to_object_id(card_id, field="card id"), "user_id": str(user_id)}
        )

    def update(self, card_id: Any, user_id: Any, fields: Dict[str, Any]) -> bool:
        payload = dict(fields)
        payload["updated_at"] = utcnow()
        result = self.collection.update_one(
            {"_id": to_object_id(card_id, field="card id"), "user_id": str(user_id)},
            {"$set": payload},
        )
        return result.matched_count > 0

    def record_review(
        self, card_id: Any, user_id: Any, *, status: str, next_due: Optional[datetime]
    ) -> bool:
        """Store a review outcome (feeds knowledge-gap detection, brief §11)."""
        result = self.collection.update_one(
            {"_id": to_object_id(card_id, field="card id"), "user_id": str(user_id)},
            {
                "$set": {
                    "review_status": status,
                    "last_reviewed_at": utcnow(),
                    "due_at": next_due,
                    "updated_at": utcnow(),
                },
                "$inc": {"review_count": 1},
            },
        )
        return result.matched_count > 0

    def delete(self, card_id: Any, user_id: Any) -> bool:
        result = self.collection.delete_one(
            {"_id": to_object_id(card_id, field="card id"), "user_id": str(user_id)}
        )
        return result.deleted_count > 0

    def delete_for_documents(self, user_id: Any, document_ids: Sequence[Any]) -> int:
        result = self.collection.delete_many(
            {"user_id": str(user_id), "document_ids": {"$in": [str(item) for item in document_ids]}}
        )
        return int(result.deleted_count)

    def topic_summary(self, user_id: Any) -> List[Dict[str, Any]]:
        """Per-topic card counts by review status (used by analytics)."""
        pipeline = [
            {"$match": {"user_id": str(user_id)}},
            {"$group": {"_id": {"topic": "$topic", "status": "$review_status"}, "count": {"$sum": 1}}},
        ]
        summary: Dict[str, Dict[str, int]] = {}
        for row in self.collection.aggregate(pipeline):
            topic = row["_id"].get("topic") or "Uncategorised"
            status = row["_id"].get("status") or "new"
            summary.setdefault(topic, {})[status] = row["count"]
        return [{"topic": topic, "statuses": statuses} for topic, statuses in summary.items()]

    def count(self, user_id: Any) -> int:
        return int(self.collection.count_documents({"user_id": str(user_id)}))


# ---------------------------------------------------------------------------
# Quizzes and attempts
# ---------------------------------------------------------------------------
class QuizRepository(BaseRepository):
    collection_key = COLLECTIONS["quizzes"]

    def create(self, quiz: Dict[str, Any]) -> str:
        return self._insert(quiz)

    def get(self, quiz_id: Any, user_id: Any) -> Optional[Dict[str, Any]]:
        return self.collection.find_one(
            {"_id": to_object_id(quiz_id, field="quiz id"), "user_id": str(user_id)}
        )

    def list_for_user(self, user_id: Any, *, page: int = 1, page_size: int = 20) -> tuple:
        query = {"user_id": str(user_id)}
        total = int(self.collection.count_documents(query))
        skip, limit, page = paginate(query, page, page_size)
        cursor = self.collection.find(query).sort("created_at", -1).skip(skip).limit(limit)
        return list(cursor), total, page, limit

    def delete(self, quiz_id: Any, user_id: Any) -> bool:
        quiz = self.get(quiz_id, user_id)
        if not quiz:
            return False
        self.collection.delete_one(
            {"_id": to_object_id(quiz_id, field="quiz id"), "user_id": str(user_id)}
        )
        # Cascade: delete all attempts for this quiz.
        attempts = QuizAttemptRepository()
        attempts.delete_for_quiz(str(quiz_id), user_id)
        return True

    def count(self, user_id: Any) -> int:
        return int(self.collection.count_documents({"user_id": str(user_id)}))

    def delete_for_documents(self, user_id: Any, document_ids: Sequence[Any]) -> int:
        """
        Delete quizzes that were generated from the given documents.

        Also removes the attempt rows that belong to those quizzes, so deleting
        a document cannot leave orphaned quiz history behind. Attempts of *other*
        quizzes are left untouched.
        """
        wanted = [str(item) for item in document_ids]
        quiz_query = {
            "user_id": str(user_id),
            "document_ids": {"$in": wanted},
        }
        quiz_ids = [str(row["_id"]) for row in self.collection.find(quiz_query, {"_id": 1})]
        deleted = int(self.collection.delete_many(quiz_query).deleted_count)
        if quiz_ids:
            # Only the attempts of the quizzes we just removed.
            QuizAttemptRepository().collection.delete_many(
                {"user_id": str(user_id), "quiz_id": {"$in": quiz_ids}}
            )
        return deleted

    def topic_names(self, user_id: Any) -> List[str]:
        """Topics that still have at least one quiz (used by analytics)."""
        rows = self.collection.find(
            {"user_id": str(user_id), "topic": {"$exists": True}}, {"topic": 1}
        )
        return [row.get("topic") or "" for row in rows]


class QuizAttemptRepository(BaseRepository):
    collection_key = COLLECTIONS["quiz_attempts"]

    def create(self, attempt: Dict[str, Any]) -> str:
        return self._insert(attempt)

    def list_for_user(self, user_id: Any, *, limit: int = 50) -> List[Dict[str, Any]]:
        return list(
            self.collection.find({"user_id": str(user_id)})
            .sort("submitted_at", -1)
            .limit(max(1, limit))
        )

    def list_for_quiz(self, quiz_id: Any, user_id: Any) -> List[Dict[str, Any]]:
        return list(
            self.collection.find({"user_id": str(user_id), "quiz_id": str(quiz_id)}).sort(
                "submitted_at", -1
            )
        )

    def delete_for_quiz(self, quiz_id: Any, user_id: Any) -> int:
        return int(
            self.collection.delete_many(
                {"user_id": str(user_id), "quiz_id": str(quiz_id)}
            ).deleted_count
        )

    def average_score(self, user_id: Any) -> Optional[float]:
        pipeline = [
            {"$match": {"user_id": str(user_id)}},
            {"$group": {"_id": None, "average": {"$avg": "$score"}}},
        ]
        rows = list(self.collection.aggregate(pipeline))
        return round(float(rows[0]["average"]), 1) if rows else None

    def count(self, user_id: Any) -> int:
        return int(self.collection.count_documents({"user_id": str(user_id)}))


# ---------------------------------------------------------------------------
# Chat sessions and messages
# ---------------------------------------------------------------------------
class ChatRepository(BaseRepository):
    collection_key = COLLECTIONS["chat_sessions"]

    @property
    def sessions(self):
        return self.collection

    @property
    def messages(self):
        return get_collection(COLLECTIONS["chat_messages"])

    def create_session(self, session: Dict[str, Any]) -> str:
        return self._insert(session)

    def get_session(self, session_id: Any, user_id: Any) -> Optional[Dict[str, Any]]:
        return self.sessions.find_one(
            {"_id": to_object_id(session_id, field="session id"), "user_id": str(user_id)}
        )

    def list_sessions(self, user_id: Any, *, limit: int = 30) -> List[Dict[str, Any]]:
        return list(
            self.sessions.find({"user_id": str(user_id)}).sort("updated_at", -1).limit(max(1, limit))
        )

    def touch_session(self, session_id: Any, *, title: Optional[str] = None) -> None:
        payload: Dict[str, Any] = {"updated_at": utcnow()}
        if title:
            payload["title"] = title
        self.sessions.update_one(
            {"_id": to_object_id(session_id)}, {"$set": payload, "$inc": {"message_count": 1}}
        )

    def delete_session(self, session_id: Any, user_id: Any) -> bool:
        session = self.get_session(session_id, user_id)
        if not session:
            return False
        self.messages.delete_many({"session_id": str(session["_id"])})
        self.sessions.delete_one({"_id": session["_id"]})
        return True

    def add_message(self, message: Dict[str, Any]) -> str:
        return self._insert(message)

    def list_messages(self, session_id: Any, *, limit: int = 200) -> List[Dict[str, Any]]:
        return list(
            self.messages.find({"session_id": str(session_id)})
            .sort("created_at", 1)
            .limit(max(1, limit))
        )

    def recent_messages(self, session_id: Any, *, limit: int = 8) -> List[Dict[str, Any]]:
        """Latest turns, returned oldest-first (RAG conversation memory)."""
        rows = list(
            self.messages.find({"session_id": str(session_id)})
            .sort("created_at", -1)
            .limit(max(1, limit))
        )
        return list(reversed(rows))


# ---------------------------------------------------------------------------
# Search logs and study events
# ---------------------------------------------------------------------------
class SearchLogRepository(BaseRepository):
    collection_key = COLLECTIONS["search_logs"]

    def create(self, log: Dict[str, Any]) -> str:
        return self._insert(log)

    def list_for_user(self, user_id: Any, *, limit: int = 50) -> List[Dict[str, Any]]:
        return list(
            self.collection.find({"user_id": str(user_id)})
            .sort("created_at", -1)
            .limit(max(1, limit))
        )

    def top_queries(self, user_id: Any, *, limit: int = 10) -> List[Dict[str, Any]]:
        """Most frequent searches — shown as "recently studied", not as a score."""
        pipeline = [
            {"$match": {"user_id": str(user_id)}},
            {
                "$group": {
                    "_id": {"$toLower": "$query"},
                    "count": {"$sum": 1},
                    "last": {"$max": "$created_at"},
                }
            },
            {"$sort": {"count": -1}},
            {"$limit": max(1, limit)},
        ]
        return [
            {"query": row["_id"], "count": row["count"], "last_searched": row["last"]}
            for row in self.collection.aggregate(pipeline)
        ]

    def count(self, user_id: Any) -> int:
        return int(self.collection.count_documents({"user_id": str(user_id)}))


class StudyEventRepository(BaseRepository):
    collection_key = COLLECTIONS["study_events"]

    def create(self, event: Dict[str, Any]) -> str:
        return self._insert(event)

    def delete_for_documents(self, user_id: Any, document_ids: Sequence[Any]) -> int:
        """
        Delete study events recorded against the given documents.

        Quiz-answer and flashcard-review events carry the ``document_ids`` of the
        material they were generated from, so removing a document can also remove
        its analytics trail (topics would otherwise live on in the knowledge-gap
        list after every trace of the material is gone).
        """
        result = self.collection.delete_many(
            {"user_id": str(user_id), "document_ids": {"$in": [str(item) for item in document_ids]}}
        )
        return int(result.deleted_count)

    def list_for_user(
        self, user_id: Any, *, event_type: Optional[str] = None, limit: int = 200
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"user_id": str(user_id)}
        if event_type:
            query["event_type"] = event_type
        return list(self.collection.find(query).sort("created_at", -1).limit(max(1, limit)))

    def correctness_by_topic(self, user_id: Any) -> List[Dict[str, Any]]:
        """Answered/correct counts per topic — the base of knowledge-gap detection."""
        pipeline = [
            {
                "$match": {
                    "user_id": str(user_id),
                    "event_type": {"$in": ["quiz_answer", "flashcard_review"]},
                }
            },
            {
                "$group": {
                    "_id": "$topic",
                    "attempts": {"$sum": 1},
                    "correct": {"$sum": {"$cond": [{"$eq": ["$correct", True]}, 1, 0]}},
                    "wrong": {"$sum": {"$cond": [{"$eq": ["$correct", False]}, 1, 0]}},
                    "last_seen": {"$max": "$created_at"},
                }
            },
            {"$sort": {"attempts": -1}},
        ]
        return [
            {
                "topic": row["_id"] or "Uncategorised",
                "attempts": row["attempts"],
                "correct": row["correct"],
                "wrong": row["wrong"],
                "last_seen": row["last_seen"],
            }
            for row in self.collection.aggregate(pipeline)
        ]

    def activity_by_day(self, user_id: Any, *, days: int = 30) -> List[Dict[str, Any]]:
        """Daily activity counts for the analytics charts."""
        pipeline = [
            {"$match": {"user_id": str(user_id)}},
            {
                "$group": {
                    "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
                    "count": {"$sum": 1},
                }
            },
            {"$sort": {"_id": 1}},
            {"$limit": max(1, days * 5)},
        ]
        return [{"date": row["_id"], "count": row["count"]} for row in self.collection.aggregate(pipeline)]

    def count(self, user_id: Any) -> int:
        return int(self.collection.count_documents({"user_id": str(user_id)}))