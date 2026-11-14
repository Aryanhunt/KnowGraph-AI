"""
Backfill ``quiz_answer`` study events from existing quiz attempts.

Older builds graded a submission and stored the attempt plus a single
``quiz_completed`` event, but never recorded the per-answer ``quiz_answer``
events that the knowledge-gap analytics read. Running this script rebuilds
those events from the answers already stored on each attempt, so historical
study activity feeds analytics without re-taking any quiz.

Idempotent: an attempt that already has ``quiz_answer`` events is skipped.

Usage (from the project root):

    backend/.venv/bin/python scripts/backfill_quiz_answer_events.py [--user-id <id>] [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild per-answer study events from quiz attempts.")
    parser.add_argument("--user-id", default=None, help="Only backfill this user's attempts.")
    parser.add_argument("--dry-run", action="store_true", help="Report counts without writing.")
    args = parser.parse_args()

    from config.settings import get_settings
    from db.mongo import init_mongo, get_mongo
    from db.repositories import to_object_id
    from db.study_repositories import StudyEventRepository

    settings = get_settings()
    init_mongo(settings)
    db = get_mongo().database
    events = StudyEventRepository()

    query: dict = {}
    if args.user_id:
        query["user_id"] = str(args.user_id)
    attempts = list(db["quiz_attempts"].find(query))
    print(f"attempts found: {len(attempts)}")

    created = skipped_attempts = missing_answers = 0
    for attempt in attempts:
        user_id = str(attempt.get("user_id"))
        quiz_id = str(attempt.get("quiz_id"))
        answers = [a for a in (attempt.get("answers") or []) if isinstance(a, dict)]
        if not answers:
            missing_answers += 1
            continue

        already = db["study_events"].count_documents(
            {"user_id": user_id, "event_type": "quiz_answer", "payload.quiz_id": quiz_id}
        )
        if already >= len(answers):
            skipped_attempts += 1
            continue

        document_ids: list = []
        try:
            quiz = db["quizzes"].find_one({"_id": to_object_id(quiz_id)})
            if quiz:
                document_ids = [str(item) for item in quiz.get("document_ids", []) or []]
        except Exception:  # noqa: BLE001 - a malformed id simply means no document link
            document_ids = []

        when = attempt.get("submitted_at") or attempt.get("created_at")
        for answer in answers:
            if args.dry_run:
                created += 1
                continue
            events.create(
                {
                    "user_id": user_id,
                    "event_type": "quiz_answer",
                    "topic": (str(answer.get("topic") or "").strip() or "Uncategorised"),
                    "document_ids": document_ids,
                    "correct": bool(answer.get("correct")),
                    "payload": {
                        "quiz_id": quiz_id,
                        "question_id": str(answer.get("question_id", "")),
                        "type": answer.get("type", "mcq"),
                        "backfilled": True,
                    },
                    "created_at": when,
                }
            )
            created += 1

    mode = "(dry-run) " if args.dry_run else ""
    print(
        f"{mode}events created: {created} | attempts skipped (already backfilled): "
        f"{skipped_attempts} | attempts without answers: {missing_answers}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
