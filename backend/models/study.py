"""
Study, chat and analytics models.

Covers flashcards, quizzes, quiz attempts, chat sessions/messages and the events
that feed knowledge-gap detection (brief §10, §11).

Quiz scoring is computed in ``quiz_service`` with plain arithmetic — never by the
LLM (brief §10).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from models.domain import utcnow

#: Difficulty labels shared by flashcards and quiz questions.
DIFFICULTIES = ("easy", "medium", "hard")

#: Quiz question types (brief §10).
QUESTION_TYPES = ("mcq", "true_false", "short_answer")

#: Chat modes (brief §8).
CHAT_MODES = (
    "knowledge",        # Ask My Knowledge — all of the user's documents
    "document",         # Chat With Document
    "subject",          # Chat With Subject
    "selected",         # Selected Documents
    "general",          # General AI (no retrieval, clearly labelled)
)

#: Analytics event kinds feeding knowledge-gap detection.
EVENT_TYPES = (
    "quiz_answer",
    "quiz_completed",
    "flashcard_review",
    "search",
    "chat_question",
    "document_view",
)


@dataclass
class Flashcard:
    """A question/answer pair generated from selected document pages."""

    user_id: str
    question: str
    answer: str
    _id: Optional[str] = None
    topic: str = ""
    difficulty: str = "medium"
    document_ids: List[str] = field(default_factory=list)
    source: Dict[str, Any] = field(default_factory=dict)   # document_id/page_number/title
    generation_method: str = "extractive"                  # llm | extractive
    review_status: str = "new"                             # new | easy | medium | hard
    review_count: int = 0
    last_reviewed_at: Optional[datetime] = None
    due_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def to_mongo(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload.pop("_id", None)
        return payload


@dataclass
class QuizQuestion:
    """One graded question. ``correct_answer`` is validated by the app."""

    question_id: str
    type: str                       # mcq | true_false | short_answer
    question: str
    correct_answer: str
    options: List[str] = field(default_factory=list)
    explanation: str = ""
    difficulty: str = "medium"
    topic: str = ""
    source: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Quiz:
    user_id: str
    title: str
    topic: str = ""
    _id: Optional[str] = None
    document_ids: List[str] = field(default_factory=list)
    questions: List[Dict[str, Any]] = field(default_factory=list)
    generation_method: str = "extractive"
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def to_mongo(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload.pop("_id", None)
        return payload


@dataclass
class QuizAttempt:
    """A graded attempt. Score is computed by application logic, not the LLM."""

    user_id: str
    quiz_id: str
    score: float                    # percentage 0..100
    correct: int
    total: int
    _id: Optional[str] = None
    answers: List[Dict[str, Any]] = field(default_factory=list)
    topic_scores: Dict[str, Any] = field(default_factory=dict)
    submitted_at: datetime = field(default_factory=utcnow)

    def to_mongo(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload.pop("_id", None)
        return payload


@dataclass
class ChatSession:
    user_id: str
    title: str = "New chat"
    _id: Optional[str] = None
    mode: str = "knowledge"
    filters: Dict[str, Any] = field(default_factory=dict)
    message_count: int = 0
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def to_mongo(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload.pop("_id", None)
        return payload


@dataclass
class ChatMessage:
    session_id: str
    user_id: str
    role: str                       # user | assistant | system
    content: str
    _id: Optional[str] = None
    mode: str = "knowledge"
    sources: List[Dict[str, Any]] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)

    def to_mongo(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload.pop("_id", None)
        return payload


@dataclass
class SearchLog:
    """Recorded so 'frequently searched topics' can be reported honestly."""

    user_id: str
    query: str
    _id: Optional[str] = None
    mode: str = "hybrid"            # hybrid | semantic | keyword
    filters: Dict[str, Any] = field(default_factory=dict)
    result_count: int = 0
    created_at: datetime = field(default_factory=utcnow)

    def to_mongo(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload.pop("_id", None)
        return payload


@dataclass
class StudyEvent:
    """One interaction that feeds knowledge-gap detection (brief §11)."""

    user_id: str
    event_type: str
    _id: Optional[str] = None
    topic: str = ""
    document_id: Optional[str] = None
    correct: Optional[bool] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)

    def to_mongo(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload.pop("_id", None)
        return payload