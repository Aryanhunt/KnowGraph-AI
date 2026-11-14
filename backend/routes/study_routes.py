"""
Study routes (``/api/study``) — flashcards and quizzes (brief §10).

Flashcards can be generated, edited, reviewed and deleted. Quizzes can be
generated, taken and submitted; **grading is plain application logic** inside
``QuizService`` (never the LLM), and every attempt is stored so analytics can use
it.
"""

from __future__ import annotations

from flask import Blueprint, request

from services.flashcard_service import FlashcardService
from services.quiz_service import QuizService
from utils.auth_middleware import current_user_id, json_body, pagination_args, require_auth
from utils.errors import ValidationError
from utils.responses import created, ok, paginated

bp = Blueprint("study", __name__, url_prefix="/api/study")


def _document_ids(payload: dict) -> list:
    """Read document ids from the body (list or comma-separated string)."""
    value = payload.get("document_ids") or []
    if isinstance(value, str):
        value = [item.strip() for item in value.split(",") if item.strip()]
    return [str(item) for item in value]


# ---------------------------------------------------------------------------
# Flashcards
# ---------------------------------------------------------------------------
@bp.post("/flashcards/generate")
@require_auth
def generate_flashcards():
    """Generate flashcards from selected documents (LLM → extractive fallback)."""
    payload = json_body()
    result = FlashcardService().generate(
        current_user_id(),
        document_ids=_document_ids(payload),
        topic=str(payload.get("topic", "")),
        count=int(payload.get("count", 8)),
    )
    return created(result)


@bp.get("/flashcards")
@require_auth
def list_flashcards():
    """List the user's flashcards with topic and review-status filters."""
    document_ids = request.args.getlist("document_ids") or None
    result = FlashcardService().list_cards(
        current_user_id(),
        document_ids=document_ids,
        topic=request.args.get("topic") or None,
        review_status=request.args.get("review_status") or None,
        **pagination_args(),
    )
    return paginated(
        result["cards"],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        extra={"topic_summary": result["topic_summary"]},
    )


@bp.get("/flashcards/<card_id>")
@require_auth
def get_flashcard(card_id: str):
    service = FlashcardService()
    return ok(service._serialize(service.get_card(current_user_id(), card_id)))


@bp.patch("/flashcards/<card_id>")
@require_auth
def update_flashcard(card_id: str):
    """Edit a card's question/answer/topic/difficulty."""
    service = FlashcardService()
    card = service.update_card(current_user_id(), card_id, json_body())
    return ok(service._serialize(card))


@bp.post("/flashcards/<card_id>/review")
@require_auth
def review_flashcard(card_id: str):
    """Record a review outcome: ``{"outcome": "easy|medium|hard"}``."""
    payload = json_body()
    outcome = str(payload.get("outcome", "")).lower()
    if not outcome:
        raise ValidationError("Provide an outcome: easy, medium or hard.", code="missing_outcome")
    service = FlashcardService()
    card = service.review_card(current_user_id(), card_id, outcome)
    return ok(service._serialize(card))


@bp.delete("/flashcards/<card_id>")
@require_auth
def delete_flashcard(card_id: str):
    FlashcardService().delete_card(current_user_id(), card_id)
    return ok({"deleted": True})


# ---------------------------------------------------------------------------
# Quizzes
# ---------------------------------------------------------------------------
@bp.post("/quizzes/generate")
@require_auth
def generate_quiz():
    """
    Generate a quiz.

    Body: ``{"document_ids": [...], "topic": "", "counts": {"mcq": 3,
    "true_false": 2, "short_answer": 1}}``
    """
    payload = json_body()
    result = QuizService().generate(
        current_user_id(),
        document_ids=_document_ids(payload),
        topic=str(payload.get("topic", "")),
        counts=payload.get("counts") or None,
    )
    return created(result)


@bp.get("/quizzes")
@require_auth
def list_quizzes():
    result = QuizService().list_quizzes(current_user_id(), **pagination_args())
    return paginated(
        result["quizzes"],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@bp.get("/quizzes/<quiz_id>")
@require_auth
def get_quiz(quiz_id: str):
    """Load a quiz. Answers are only included when ``?include_answers=true``."""
    include = request.args.get("include_answers", "false").lower() in ("1", "true", "yes")
    return ok(QuizService().get_quiz(current_user_id(), quiz_id, include_answers=include))


@bp.post("/quizzes/<quiz_id>/submit")
@require_auth
def submit_quiz(quiz_id: str):
    """
    Submit answers: ``{"answers": {"<question_id>": "answer", ...}}``.

    Scoring happens in ``QuizService`` with explicit comparison rules; the same
    method records the attempt and the per-topic results used by analytics.
    """
    payload = json_body()
    answers = payload.get("answers")
    if not isinstance(answers, dict) or not answers:
        raise ValidationError(
            "Provide answers as {\"answers\": {\"<question_id>\": \"...\"}}.",
            code="missing_answers",
        )
    return ok(QuizService().submit(current_user_id(), quiz_id, answers))


@bp.get("/quizzes/<quiz_id>/attempts")
@require_auth
def quiz_attempts(quiz_id: str):
    """Previous attempts for one quiz (so a student can see progress)."""
    return ok(QuizService().attempts_for_quiz(current_user_id(), quiz_id))


@bp.delete("/quizzes/<quiz_id>")
@require_auth
def delete_quiz(quiz_id: str):
    QuizService().delete_quiz(current_user_id(), quiz_id)
    return ok({"deleted": True})