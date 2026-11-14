"""
Analytics and knowledge-gap detection (brief §11).

Deliberately *not* an "AI confidence score". Everything here is computed from
recorded facts:

* quiz answers and flashcard reviews (``study_events``),
* searches performed (``search_logs``),
* how recently a topic was touched.

Topics are labelled in plain language:

    Strong | Needs Revision | Frequently Missed | Recently Studied | Not Yet Studied

Any percentage shown is an exact ratio of recorded answers (correct/attempts), so
every number can be explained line by line in a viva.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from config.settings import Settings, get_settings
from db.repositories import DocumentRepository
from db.study_repositories import (
    FlashcardRepository,
    QuizAttemptRepository,
    QuizRepository,
    SearchLogRepository,
    StudyEventRepository,
)
from datetime import timezone

from models.domain import utcnow
from utils.logging_setup import get_logger

logger = get_logger(__name__)

#: Label thresholds — simple documented constants instead of a hidden model.
STRONG_ACCURACY = 0.80
WEAK_ACCURACY = 0.50
MIN_ATTEMPTS_FOR_STRENGTH = 3
RECENT_DAYS = 7
STALE_DAYS = 21

LABEL_STRONG = "Strong"
LABEL_NEEDS_REVISION = "Needs Revision"
LABEL_FREQUENTLY_MISSED = "Frequently Missed"
LABEL_RECENTLY_STUDIED = "Recently Studied"
LABEL_NOT_STUDIED = "Not Yet Studied"


class AnalyticsService:
    """Aggregates learning data into progress views and gap lists."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        documents: Optional[DocumentRepository] = None,
        events: Optional[StudyEventRepository] = None,
        quizzes: Optional[QuizRepository] = None,
        attempts: Optional[QuizAttemptRepository] = None,
        cards: Optional[FlashcardRepository] = None,
        logs: Optional[SearchLogRepository] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.documents = documents or DocumentRepository()
        self.events = events or StudyEventRepository()
        self.quizzes = quizzes or QuizRepository()
        self.attempts = attempts or QuizAttemptRepository()
        self.cards = cards or FlashcardRepository()
        self.logs = logs or SearchLogRepository()

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    def dashboard(self, user_id: Any) -> Dict[str, Any]:
        """Counts and recent activity for the dashboard page."""
        user_id = str(user_id)
        return {
            "documents": self.documents.stats(user_id),
            "flashcards": {
                "total": self.cards.count(user_id),
                "by_topic": self.cards.topic_summary(user_id),
            },
            "quizzes": {
                "total": self.quizzes.count(user_id),
                "attempts": self.attempts.count(user_id),
                "average_score": self.attempts.average_score(user_id),
            },
            "searches": self.logs.count(user_id),
            "recent_searches": self.logs.list_for_user(user_id, limit=5),
            "recent_documents": self.documents.recent(user_id, limit=5),
            "activity": self.events.activity_by_day(user_id, days=30),
            "in_progress_documents": self.documents.count_in_progress(user_id),
        }


    # ------------------------------------------------------------------
    # Knowledge gaps
    # ------------------------------------------------------------------
    def topic_status(self, user_id: Any) -> List[Dict[str, Any]]:
        """
        One row per topic with transparent labels (brief §11).

        Each row carries the raw numbers the label was derived from, so the UI can
        justify every statement it makes. Topics taken from the user's documents
        are included as well: uploaded material is a topic from the moment the
        file is processed, so "All topics" and the knowledge-gap view are never
        empty just because no quiz has been taken yet.
        """
        user_id = str(user_id)
        rows = self.events.correctness_by_topic(user_id)
        now = utcnow()

        # Every recorded event is a recorded fact: a quiz that was later deleted
        # does not un-answer the questions the user already attempted, so event
        # topics are always kept. Topics from the user's documents are included
        # as well: uploaded material is a topic from the moment the file is
        # processed, so "All topics" and the knowledge-gap view are never empty
        # just because no quiz has been taken yet.

        # Topics that still have study material (flashcards or quizzes), used to
        # annotate event topics whose original material was deleted.
        document_topics: List[str] = []
        for document in self.documents.list_all_for_user(user_id, only_ready=False):
            for name in document.get("topics", []) or []:
                cleaned = str(name).strip()
                if cleaned:
                    document_topics.append(cleaned)
        in_document = {name.lower() for name in document_topics}

        def _entry(
            topic: str,
            *,
            attempts: int,
            correct: int,
            wrong: int,
            last_seen: Any,
            explanation: Optional[str] = None,
        ) -> Dict[str, Any]:
            accuracy = round(correct / attempts, 3) if attempts else None
            if last_seen is not None and getattr(last_seen, "tzinfo", None) is None:
                # MongoDB returns naive UTC datetimes from aggregations.
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            days_since = (now - last_seen).days if last_seen else None
            label = self._label_for(
                attempts=attempts, accuracy=accuracy, wrong=wrong, days_since=days_since
            )
            return {
                "topic": topic,
                "attempts": attempts,
                "correct": correct,
                "wrong": wrong,
                "accuracy": accuracy,
                "last_seen": last_seen,
                "days_since_review": days_since,
                "status": label,
                "explanation": explanation or self._explain(label, attempts, correct, days_since),
            }

        topics: List[Dict[str, Any]] = []
        seen: set = set()
        for row in rows:
            topic_name = (row.get("topic") or "Uncategorised").strip() or "Uncategorised"
            # Recorded answers are facts: a topic with quiz/flashcard activity is
            # always reported, even when the quiz or flashcard deck behind it was
            # deleted — otherwise real knowledge gaps (wrong answers) silently
            # vanish and the knowledge-gap view shows nothing weak.
            if int(row.get("attempts", 0)) <= 0 and topic_name.lower() not in in_document:
                continue
            seen.add(topic_name.lower())
            source_gone = (
                topic_name.lower() not in in_document
                and int(row.get("attempts", 0)) > 0
            )
            topics.append(
                _entry(
                    topic_name,
                    attempts=int(row.get("attempts", 0)),
                    correct=int(row.get("correct", 0)),
                    wrong=int(row.get("wrong", 0)),
                    last_seen=row.get("last_seen"),
                    explanation=(
                        "Original quiz or flashcard for this topic was deleted; "
                        "these answers are still counted."
                        if source_gone
                        else None
                    ),
                )
            )

        for name in document_topics:
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            topics.append(
                _entry(
                    name,
                    attempts=0,
                    correct=0,
                    wrong=0,
                    last_seen=None,
                    explanation="Topic found in your documents but not studied yet.",
                )
            )

        order = {
            LABEL_FREQUENTLY_MISSED: 0,
            LABEL_NEEDS_REVISION: 1,
            LABEL_RECENTLY_STUDIED: 2,
            LABEL_STRONG: 3,
            LABEL_NOT_STUDIED: 4,
        }
        topics.sort(key=lambda item: (order.get(item["status"], 5), -(item["attempts"] or 0)))
        return topics

    @staticmethod
    def _label_for(
        *, attempts: int, accuracy: Optional[float], wrong: int, days_since: Optional[int]
    ) -> str:
        """Map recorded numbers to one of the five transparent labels."""
        if attempts == 0:
            return LABEL_NOT_STUDIED
        if accuracy is not None and attempts >= MIN_ATTEMPTS_FOR_STRENGTH:
            if accuracy >= STRONG_ACCURACY:
                return LABEL_STRONG
            if accuracy < WEAK_ACCURACY and wrong >= 2:
                return LABEL_FREQUENTLY_MISSED
            return LABEL_NEEDS_REVISION
        # Too few answers so far: report recency instead of a shaky accuracy claim.
        if days_since is not None and days_since <= RECENT_DAYS:
            return LABEL_RECENTLY_STUDIED
        if accuracy is not None and accuracy >= STRONG_ACCURACY:
            return LABEL_STRONG
        return LABEL_NEEDS_REVISION

    @staticmethod
    def _explain(label: str, attempts: int, correct: int, days_since: Optional[int]) -> str:
        if label == LABEL_NOT_STUDIED:
            return "No quiz or flashcard activity recorded for this topic yet."
        if label == LABEL_STRONG:
            return f"{correct} of {attempts} answered correctly — keep it ticking over."
        if label == LABEL_FREQUENTLY_MISSED:
            return f"Only {correct} of {attempts} answered correctly — review this topic first."
        if label == LABEL_RECENTLY_STUDIED:
            return f"Studied recently ({attempts} answers so far) — not enough data to judge yet."
        when = f"{days_since} days ago" if days_since is not None else "some time ago"
        return f"Last reviewed {when} — worth another pass."


    def knowledge_gaps(self, user_id: Any, *, limit: int = 10) -> Dict[str, Any]:
        """Weak topics plus topics that have not been revised for a long time."""
        topics = self.topic_status(user_id)
        weak = [
            topic
            for topic in topics
            if topic["status"] in (LABEL_FREQUENTLY_MISSED, LABEL_NEEDS_REVISION)
        ]
        stale = [
            topic
            for topic in topics
            if topic["days_since_review"] is not None and topic["days_since_review"] >= STALE_DAYS
        ]
        not_studied = [topic for topic in topics if topic["status"] == LABEL_NOT_STUDIED]
        return {
            "weak_topics": weak[:limit],
            "not_revised_recently": stale[:limit],
            "not_studied": not_studied[:limit],
            "frequently_searched": self.logs.top_queries(user_id, limit=5),
            "all_topics": topics,
            "legend": {
                LABEL_STRONG: f">= {int(STRONG_ACCURACY * 100)}% correct with at least "
                              f"{MIN_ATTEMPTS_FOR_STRENGTH} answers",
                LABEL_NEEDS_REVISION: f"below {int(STRONG_ACCURACY * 100)}% correct, or too few answers",
                LABEL_FREQUENTLY_MISSED: f"below {int(WEAK_ACCURACY * 100)}% correct with several mistakes",
                LABEL_RECENTLY_STUDIED: f"studied within the last {RECENT_DAYS} days",
                LABEL_NOT_STUDIED: "no recorded activity yet",
            },
        }

    def progress(self, user_id: Any) -> Dict[str, Any]:
        """Per-subject grouping of topics for the progress dashboard (§11)."""
        user_id = str(user_id)
        topics = {topic["topic"].lower(): topic for topic in self.topic_status(user_id)}
        subjects: Dict[str, List[Dict[str, Any]]] = {}

        for document in self.documents.list_all_for_user(user_id, only_ready=False):
            subject = (document.get("subject") or "Uncategorised").strip() or "Uncategorised"
            bucket = subjects.setdefault(subject, [])
            for topic in document.get("topics", []) or []:
                key = str(topic).lower()
                entry = topics.get(key) or {
                    "topic": str(topic),
                    "attempts": 0,
                    "correct": 0,
                    "wrong": 0,
                    "accuracy": None,
                    "last_seen": None,
                    "days_since_review": None,
                    "status": LABEL_NOT_STUDIED,
                    "explanation": "Topic found in your documents but not studied yet.",
                }
                if entry not in bucket:
                    bucket.append(entry)

        return {
            "subjects": [
                {"subject": subject, "topics": sorted(items, key=lambda item: item["status"])}
                for subject, items in sorted(subjects.items())
            ],
            "summary": {
                "topics_with_activity": sum(1 for topic in topics.values() if topic["attempts"]),
                "strong_topics": sum(
                    1 for topic in topics.values() if topic["status"] == LABEL_STRONG
                ),
                "weak_topics": sum(
                    1
                    for topic in topics.values()
                    if topic["status"] in (LABEL_FREQUENTLY_MISSED, LABEL_NEEDS_REVISION)
                ),
            },
        }


def get_analytics_service(settings: Optional[Settings] = None) -> AnalyticsService:
    """Convenience factory used by the analytics routes."""
    return AnalyticsService(settings)
