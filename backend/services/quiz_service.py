"""
Quiz service (brief §10).

Generation mirrors the flashcards: the local model writes questions from retrieved
excerpts when it is available; otherwise MCQ / true-false / short-answer questions
are built deterministically from definition sentences. Either way every question
carries the excerpt it came from.

Scoring is **plain application logic** (brief §10): answers are compared with a
normalised string match, the score is ``correct / total * 100``, and per-topic
totals are aggregated with simple arithmetic. The LLM is never asked to grade.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config.settings import Settings, get_settings
from db.repositories import DocumentRepository, PageRepository
from db.study_repositories import (
    FlashcardRepository,
    QuizAttemptRepository,
    QuizRepository,
    StudyEventRepository,
)
from models.study import QUESTION_TYPES
from services.llm import prompts
from services.llm.factory import get_llm_service
from services.search_service import SearchService
from utils.errors import NotFoundError, ValidationError
from utils.logging_setup import get_logger
from utils.text import is_meaningful_text, normalize_for_match, split_sentences, truncate

logger = get_logger(__name__)

_QUESTION_ID_RE = re.compile(r"q\d+")

#: "X is/are/means ..." sentences — used to build definition-based questions.
_DEFINITION_RE = re.compile(
    r"^(?P<term>[A-Za-z][\w\s\-']{2,50}?)\s+(?:is|are|means)\s+(?P<body>.{20,400})$",
    re.IGNORECASE,
)

#: A single letter is an option *label*, never option *content*.
OPTION_LETTER = re.compile(r"^[A-Ja-j]$")


def is_option_letter(text) -> bool:
    """True when a string is just an option label like "A" or "c"."""
    return bool(OPTION_LETTER.match(str(text or "").strip()))


def align_mcq_answer(raw_options, cleaned_options, correct: str) -> str:
    """Align `correct_answer` with the cleaned option list.

    Handles every shape a small local model produces: letter prefixes on the
    options ("B. Consistency"), a bare-letter answer ("B") with full-text
    options (mapped onto the matching option), and already-clean input.
    """
    options_text = [str(option).strip() for option in cleaned_options]
    correct = (correct or "").strip()

    letter_match = re.match(r"^([A-Ja-j])[.)]\s+(.*)$", correct)
    if letter_match:
        letter = letter_match.group(1).upper()
        for original, cleaned in zip(raw_options, options_text):
            original_letter = re.match(r"^([A-Ja-j])[.)]", str(original).strip())
            if original_letter and original_letter.group(1).upper() == letter:
                return cleaned
        return letter_match.group(2).strip()

    if len(correct) == 1 and correct.isalpha():
        index = ord(correct.upper()) - ord("A")
        if 0 <= index < len(options_text):
            return options_text[index]
        return correct

    for original, cleaned in zip(raw_options, options_text):
        if original != cleaned and (correct in str(original) or str(original) in correct):
            return cleaned
    return correct


def valid_mcq_options(options) -> bool:
    """An MCQ option list is usable only when it holds real answer texts."""
    texts = [str(option).strip() for option in (options or [])]
    return len(texts) >= 2 and any(len(text) > 3 for text in texts)


#: Excerpts per generation call (prompt size guard).
MAX_EXCERPTS = 8


class QuizService:
    """Generate, store, take and score quizzes."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        quizzes: Optional[QuizRepository] = None,
        attempts: Optional[QuizAttemptRepository] = None,
        documents: Optional[DocumentRepository] = None,
        pages: Optional[PageRepository] = None,
        cards: Optional[FlashcardRepository] = None,
        search: Optional[SearchService] = None,
        events: Optional[StudyEventRepository] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.quizzes = quizzes or QuizRepository()
        self.attempts = attempts or QuizAttemptRepository()
        self.documents = documents or DocumentRepository()
        self.pages = pages or PageRepository()
        self.cards = cards or FlashcardRepository()
        self.search = search or SearchService(self.settings)
        self.events = events or StudyEventRepository()

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    def generate(
        self,
        user_id: Any,
        *,
        document_ids: Sequence[Any],
        topic: str = "",
        counts: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """
        Generate a quiz from the selected documents.

        ``counts`` maps question type → amount, e.g.
        ``{"mcq": 3, "true_false": 2, "short_answer": 1}``.
        """
        user_id = str(user_id)
        wanted = self._normalise_counts(counts)
        document_ids = [str(item) for item in document_ids or []]
        if not document_ids:
            raise ValidationError(
                "Select at least one document to generate a quiz from.",
                code="no_documents_selected",
            )
        if not any(wanted.values()):
            raise ValidationError(
                "Choose at least one question of any type.",
                code="no_questions_requested",
            )

        owned = self.documents.list_all_for_user(
            user_id, only_ready=True, document_ids=document_ids
        )
        if not owned:
            raise ValidationError(
                "The selected documents are not ready yet.",
                hint="Wait for processing to finish, then try again.",
                code="documents_not_ready",
            )
        title_map = {str(row["_id"]): row.get("title", "") for row in owned}

        excerpts = self._collect_excerpts(user_id, document_ids, topic)
        if not excerpts:
            raise ValidationError(
                "No readable text was found in the selected documents.",
                code="no_text_for_quiz",
            )

        questions: List[Dict[str, Any]] = []
        method = "extractive"
        if self._llm_available():
            questions = self._generate_with_llm(topic, excerpts, wanted)
            if questions:
                method = "llm"
        missing_total = sum(wanted.values()) - len(questions)
        if missing_total > 0:
            questions.extend(self._generate_extractive(excerpts, missing_total, used=questions))

        questions = [q for q in questions if self._validate_question(q)][: sum(wanted.values())]
        if not questions:
            raise ValidationError(
                "Quiz questions could not be generated from this material.",
                code="no_questions_generated",
                hint="The text may be too short or too repetitive — try another document.",
            )

        quiz_id = self.quizzes.create(
            {
                "user_id": user_id,
                "title": truncate(topic.strip() or "Generated quiz", 120),
                "topic": truncate(topic.strip(), 120),
                "document_ids": document_ids,
                "questions": questions,
                "generation_method": method,
            }
        )
        logger.info("Generated quiz %s with %s questions (%s)", quiz_id, len(questions), method)
        return {
            "id": str(quiz_id),
            "title": truncate(topic.strip() or "Generated quiz", 120),
            "topic": topic,
            "question_count": len(questions),
            "generation_method": method,
            "documents": [
                {"document_id": document_id, "title": title_map.get(document_id, "")}
                for document_id in document_ids
            ],
        }

    # ------------------------------------------------------------------
    # Generation internals
    # ------------------------------------------------------------------
    @staticmethod
    def _normalise_counts(counts: Optional[Dict[str, int]]) -> Dict[str, int]:
        wanted = {"mcq": 0, "true_false": 0, "short_answer": 0}
        for key, value in (counts or {}).items():
            if key in wanted:
                try:
                    wanted[key] = max(0, min(20, int(value)))
                except (TypeError, ValueError):
                    continue
        return wanted

    def _llm_available(self) -> bool:
        try:
            return get_llm_service(self.settings).is_available()
        except Exception:  # noqa: BLE001
            return False

    def _collect_excerpts(
        self, user_id: str, document_ids: Sequence[str], topic: str
    ) -> List[Dict[str, Any]]:
        """Same retrieval strategy as flashcards: topic search first, then pages."""
        excerpts: List[Dict[str, Any]] = []
        seen: set = set()
        if topic.strip():
            for hit in self.search.search(
                user_id, topic, mode="hybrid", document_ids=list(document_ids), top_k=MAX_EXCERPTS
            ):
                key = (hit.document_id, hit.page_number)
                if key in seen or not is_meaningful_text(hit.text, 80):
                    continue
                seen.add(key)
                excerpts.append(
                    {
                        "document_id": hit.document_id,
                        "title": hit.document_title,
                        "page_number": hit.page_number,
                        "text": hit.text,
                    }
                )
        for document_id in document_ids:
            for page in self.pages.list_for_document(document_id):
                key = (document_id, page.get("page_number"))
                if key in seen or not is_meaningful_text(page.get("text", ""), 80):
                    continue
                seen.add(key)
                excerpts.append(
                    {
                        "document_id": document_id,
                        "title": "",
                        "page_number": page.get("page_number"),
                        "text": page.get("text", ""),
                    }
                )
                if len(excerpts) >= MAX_EXCERPTS:
                    return excerpts
        return excerpts

    def _generate_with_llm(
        self, topic: str, excerpts: Sequence[Dict[str, Any]], wanted: Dict[str, int]
    ) -> List[Dict[str, Any]]:
        try:
            llm = get_llm_service(self.settings)
            payload = llm.generate_json(
                prompts.build_quiz_prompt(topic, list(excerpts), wanted),
                system=prompts.QUIZ_SYSTEM,
                max_tokens=1600,
            )
        except Exception as exc:  # noqa: BLE001 - fall back to deterministic questions
            logger.warning("LLM quiz generation failed: %s", exc)
            return []
        if not payload:
            return []

        questions: List[Dict[str, Any]] = []
        for index, item in enumerate(payload.get("questions", []) or [], start=1):
            if not isinstance(item, dict):
                continue
            q_type = str(item.get("type", "mcq")).strip().lower()
            if q_type not in QUESTION_TYPES:
                q_type = "mcq"
            raw_options = [str(option).strip() for option in (item.get("options") or [])]
            correct = str(item.get("correct_answer", "")).strip()
            # Models often prefix options with "A. ", "B) ", "1. " themselves. The
            # UI already renders radio buttons, so strip those prefixes - and the
            # matching prefix from correct_answer, so grading still compares the
            # same strings.
            cleaned_options = []
            for option in raw_options:
                cleaned = re.sub(r"^[A-Ja-j][.)]\s+", "", option)
                cleaned_options.append(cleaned if cleaned else option)
            correct = align_mcq_answer(raw_options, cleaned_options, correct)
            if q_type == "mcq" and not valid_mcq_options(cleaned_options):
                # The model sent labels instead of answer texts (or nothing).
                # Reject it so `generate()` backfills a deterministic question.
                logger.info("Rejecting malformed MCQ options: %r", raw_options[:4])
                return None
            question = self._build_question(
                question_id=f"q{index}",
                q_type=q_type,
                question=str(item.get("question", "")).strip(),
                options=cleaned_options,
                correct=correct,
                explanation=str(item.get("explanation", "")).strip(),
                difficulty=str(item.get("difficulty", "medium")).strip().lower(),
                topic=str(item.get("topic", "")).strip(),
                source_index=int(item.get("source_excerpt", 1) or 1),
                excerpts=excerpts,
            )
            if question:
                questions.append(question)
        return questions

    def _build_question(
        self,
        *,
        question_id: str,
        q_type: str,
        question: str,
        options: List[str],
        correct: str,
        explanation: str,
        difficulty: str,
        topic: str,
        source_index: int,
        excerpts: Sequence[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Validate one question and attach its source metadata."""
        if not question or not correct:
            return None
        if q_type == "mcq" and not valid_mcq_options(options):
            return None
        if q_type == "mcq" and correct and is_option_letter(correct):
            return None
        if q_type == "true_false":
            options = ["True", "False"]
            if correct.strip().lower() not in ("true", "false"):
                return None
            correct = correct.strip().title()
        excerpt_index = source_index if 0 < source_index <= len(excerpts) else 1
        excerpt = excerpts[excerpt_index - 1]
        return {
            "question_id": question_id,
            "type": q_type,
            "question": truncate(question, 400),
            "options": options[:6],
            "correct_answer": truncate(correct, 300),
            "explanation": truncate(explanation, 600),
            "difficulty": difficulty if difficulty in ("easy", "medium", "hard") else "medium",
            "topic": truncate(topic, 120),
            "source": {
                "document_id": excerpt["document_id"],
                "title": excerpt.get("title", ""),
                "page_number": excerpt.get("page_number"),
            },
        }

    @staticmethod
    def _validate_question(question: Dict[str, Any]) -> bool:
        if not (question and question.get("question") and question.get("correct_answer")):
            return False
        if question.get("type") == "mcq":
            if not valid_mcq_options(question.get("options")):
                return False
            if is_option_letter(question.get("correct_answer")):
                return False
        return True

    # ------------------------------------------------------------------
    # Deterministic question generation (no model required)
    # ------------------------------------------------------------------
    _DEFINITION_RE = re.compile(
        r"^(?P<term>[A-Za-z][\w\s\-']{2,50}?)\s+(?:is|are|means)\s+(?P<body>.{20,400})$",
        re.IGNORECASE,
    )

    def _generate_extractive(
        self,
        excerpts: Sequence[Dict[str, Any]],
        count: int,
        *,
        used: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Build questions with plain string logic.

        MCQs come from definition sentences ("What is X?" plus distractors drawn
        from other definitions in the same material), true/false statements flip a
        term to produce a false claim, and short answers ask for a definition.
        """
        from utils.text import clean_concept_label

        wanted = count
        definitions: List[Tuple[str, str, Dict[str, Any]]] = []   # (term, body, excerpt)
        for excerpt in excerpts:
            for sentence in split_sentences(excerpt.get("text", "")):
                if not is_meaningful_text(sentence, 60) or len(sentence) > 400:
                    continue
                match = self._DEFINITION_RE.match(sentence.strip())
                if not match:
                    continue
                term = clean_concept_label(match.group("term"))
                body = match.group("body").strip().rstrip(".")
                if term and 1 <= len(term.split()) <= 6 and len(body) >= 25:
                    definitions.append((term, truncate(body, 300), excerpt))
                if len(definitions) >= wanted * 2:
                    break

        existing = {str(item.get("question", "")).lower() for item in used}
        questions: List[Dict[str, Any]] = []
        serial = len(used) + 1

        for position, (term, body, excerpt) in enumerate(definitions):
            if len(questions) >= wanted:
                break
            source_index = next(
                (i for i, item in enumerate(excerpts, start=1) if item is excerpt), 1
            )
            other_terms = [
                other_term
                for other_position, (other_term, _b, _e) in enumerate(definitions)
                if other_position != position and other_term.lower() != term.lower()
            ]
            other_terms = list(dict.fromkeys(other_terms))[:3]

            # Extractive MCQ format: the stem names the *important term* asked for
            # (with the definition as the proving context) and the options are
            # terms — never literal "A/B/C/D" letters and never bare definitions.
            # `correct_answer` carries the term first, then the evidence text, so
            # grading and the result panel can use either half.
            question_text = (
                f"Which term is defined as follows?\n\"{truncate(body, 160)}\""
            )
            term_options = [term] + other_terms[:3]
            if len(term_options) >= 2 and question_text.lower() not in existing:
                questions.append(
                    self._build_question(
                        question_id=f"q{serial}",
                        q_type="mcq",
                        question=question_text,
                        options=term_options,
                        correct=f"{term} — {truncate(body, 140)}",
                        explanation=f"Your notes define {term} as: {truncate(body, 200)}",
                        difficulty="medium",
                        topic=term,
                        source_index=source_index,
                        excerpts=excerpts,
                    )
                )
                existing.add(question_text.lower())
                serial += 1

            tf_text = f"{term} is {body}."
            if len(questions) < wanted and tf_text.lower() not in existing:
                other_term = next(
                    (
                        other
                        for other_position, (other, _b, _e) in enumerate(definitions)
                        if other_position != position and other.lower() != term.lower()
                    ),
                    None,
                )
                if other_term and len(questions) % 2 == 1:
                    statement = f"{other_term} is {body}."
                    correct = "False"
                    explanation = (
                        f"That statement describes {term}, not {other_term}. "
                        f"Your notes define {term} as: {truncate(body, 200)}"
                    )
                else:
                    statement = tf_text
                    correct = "True"
                    explanation = "This is stated directly in your notes."
                questions.append(
                    self._build_question(
                        question_id=f"q{serial}",
                        q_type="true_false",
                        question=statement,
                        options=["True", "False"],
                        correct=correct,
                        explanation=explanation,
                        difficulty="easy",
                        topic=term,
                        source_index=source_index,
                        excerpts=excerpts,
                    )
                )
                existing.add(tf_text.lower())
                serial += 1

            # Understanding-oriented stems instead of a bare "Define: X" —
            # the rotation keeps consecutive short answers feeling different.
            sa_templates = [
                f"Define: {term}.",
                f"Explain in your own words what {term} means.",
                f"State the rule or purpose behind {term}.",
                f"How would you describe {term} to a classmate before the exam?",
            ]
            sa_text = sa_templates[(serial - 1) % len(sa_templates)]
            if len(questions) < wanted and sa_text.lower() not in existing:
                questions.append(
                    self._build_question(
                        question_id=f"q{serial}",
                        q_type="short_answer",
                        question=sa_text,
                        options=[],
                        correct=body,
                        explanation=(
                            f"Expected answer from your notes: {truncate(body, 200)} — "
                            f"any explanation covering these ideas in your own words counts."
                        ),
                        difficulty="hard",
                        topic=term,
                        source_index=source_index,
                        excerpts=excerpts,
                    )
                )
                existing.add(sa_text.lower())
                serial += 1

        return [question for question in questions if question]

    # ------------------------------------------------------------------
    # Taking and grading (plain application logic, brief §10)
    # ------------------------------------------------------------------
    def get_quiz(self, user_id: Any, quiz_id: Any, *, include_answers: bool = False) -> Dict[str, Any]:
        """Load a quiz; answers are stripped unless explicitly requested."""
        quiz = self.quizzes.get(quiz_id, user_id)
        if not quiz:
            raise NotFoundError("Quiz not found.", code="quiz_not_found")
        return self._serialize_quiz(quiz, include_answers=include_answers)

    def submit(self, user_id: Any, quiz_id: Any, answers: Dict[str, Any]) -> Dict[str, Any]:
        """
        Grade a submission and store the attempt.

        Comparison rules (deterministic, shown to the user):
        * ``mcq`` / ``true_false`` — exact match after normalisation,
        * ``short_answer`` — accepted when either answer contains the other, or
          every significant word of the shorter answer appears in the longer one
          (so "A superkey determinant" matches "every determinant must be a
          superkey"). Case/punctuation/word-order insensitive.
        """
        quiz = self.quizzes.get(quiz_id, user_id)
        if not quiz:
            raise NotFoundError("Quiz not found.", code="quiz_not_found")

        answers = answers or {}
        results: List[Dict[str, Any]] = []
        topic_stats: Dict[str, Dict[str, int]] = {}

        for question in quiz.get("questions", []):
            question_id = str(question.get("question_id"))
            given = str(answers.get(question_id, "") or "").strip()
            expected = str(question.get("correct_answer", "")).strip()
            q_type = question.get("type", "mcq")

            if q_type in ("mcq", "true_false"):
                is_correct = normalize_for_match(given) == normalize_for_match(expected)
            else:
                is_correct = self._grade_short_answer(given, expected)

            topic = question.get("topic") or "Uncategorised"
            stats = topic_stats.setdefault(topic, {"attempts": 0, "correct": 0})
            stats["attempts"] += 1
            stats["correct"] += 1 if is_correct else 0

            results.append(
                {
                    "question_id": question_id,
                    "topic": topic,
                    "type": q_type,
                    "given_answer": given,
                    "correct_answer": expected,
                    "correct": is_correct,
                    "explanation": question.get("explanation", ""),
                    "source": question.get("source", {}),
                }
            )
            try:
                self.events.create(
                    {
                        "user_id": str(user_id),
                        "event_type": "quiz_answer",
                        "topic": topic,
                        "document_ids": [str(item) for item in quiz.get("document_ids", [])],
                        "correct": is_correct,
                        "payload": {
                            "quiz_id": str(quiz_id),
                            "question_id": question_id,
                            "type": q_type,
                        },
                    }
                )
            except Exception as exc:  # noqa: BLE001 - analytics logging is best-effort
                logger.warning("Could not record quiz answer event: %s", exc)

        total = len(results)
        correct_count = sum(1 for item in results if item["correct"])
        score = round((correct_count / total) * 100, 1) if total else 0.0

        attempt_id = self.attempts.create(
            {
                "user_id": str(user_id),
                "quiz_id": str(quiz_id),
                "score": score,
                "correct": correct_count,
                "total": total,
                "answers": results,
                "topic_scores": self._topic_percentages(topic_stats),
            }
        )
        try:
            self.events.create(
                {
                    "user_id": str(user_id),
                    "event_type": "quiz_completed",
                    "topic": quiz.get("topic", ""),
                    "document_ids": [str(item) for item in quiz.get("document_ids", [])],
                    "payload": {"quiz_id": str(quiz_id), "score": score, "total": total},
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record quiz completion: %s", exc)

        return {
            "attempt_id": str(attempt_id),
            "quiz_id": str(quiz_id),
            "score": score,
            "correct": correct_count,
            "total": total,
            "topic_scores": self._topic_percentages(topic_stats),
            "results": results,
        }

    #: Short-answer grading thresholds (documented so results are explainable):
    #: at least MIN_SA_WORDS significant words of the student's own, covering at
    #: least MIN_SA_COVERAGE of the expected answer's significant words.
    MIN_SA_WORDS = 3
    MIN_SA_COVERAGE = 0.5

    @classmethod
    def _grade_short_answer(cls, given: str, expected: str) -> bool:
        """Coverage-based, word-order tolerant grading for short answers.

        A verbatim (or contained) answer passes immediately. Otherwise the
        student's answer needs at least :data:`MIN_SA_WORDS` significant words of
        their own **and** must cover at least :data:`MIN_SA_COVERAGE` of the
        expected answer's significant words — so "determinant superkey" (two
        keywords) is not enough when the expected answer has four, but a genuine
        paraphrase covering most of the idea is accepted regardless of wording.
        """
        given_norm = normalize_for_match(given)
        expected_norm = normalize_for_match(expected)
        if not given_norm or not expected_norm:
            return False
        if expected_norm in given_norm or given_norm in expected_norm:
            return True

        given_words = {word for word in given_norm.split() if len(word) > 2}
        expected_words = {word for word in expected_norm.split() if len(word) > 2}
        if not given_words or not expected_words:
            return False
        if len(given_words) < cls.MIN_SA_WORDS:
            return False
        given_keys = {cls._stem_key(word) for word in given_words}
        expected_keys = {cls._stem_key(word) for word in expected_words}
        coverage = len(given_keys & expected_keys) / len(expected_keys)
        return coverage >= cls.MIN_SA_COVERAGE

    @staticmethod
    def _stem_key(word: str) -> str:
        stem = word
        if len(stem) > 3:
            if stem.endswith("ies"):
                stem = stem[:-3] + "y"
            elif stem.endswith(("sses", "xes", "ches", "shes", "oes")):
                stem = stem[:-2]
            elif stem.endswith("ses"):
                stem = stem[:-1]
            elif stem.endswith("s") and not stem.endswith("ss"):
                stem = stem[:-1]
        return stem

    @staticmethod
    def _topic_percentages(topic_stats: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, Any]]:
        return {
            topic: {
                "correct": stats["correct"],
                "attempts": stats["attempts"],
                "percentage": round(stats["correct"] / stats["attempts"] * 100, 1)
                if stats["attempts"]
                else 0.0,
            }
            for topic, stats in topic_stats.items()
        }

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------
    def list_quizzes(self, user_id: Any, *, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        quizzes, total, page, page_size = self.quizzes.list_for_user(
            user_id, page=page, page_size=page_size
        )
        return {
            "quizzes": [self._serialize_quiz(quiz, include_answers=False) for quiz in quizzes],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def attempts_for_quiz(self, user_id: Any, quiz_id: Any) -> List[Dict[str, Any]]:
        self.get_quiz(user_id, quiz_id)
        return [
            {
                "id": str(attempt["_id"]),
                "score": attempt.get("score", 0.0),
                "correct": attempt.get("correct", 0),
                "total": attempt.get("total", 0),
                "topic_scores": attempt.get("topic_scores", {}),
                "submitted_at": attempt.get("submitted_at"),
            }
            for attempt in self.attempts.list_for_quiz(quiz_id, user_id)
        ]

    def delete_quiz(self, user_id: Any, quiz_id: Any) -> bool:
        self.get_quiz(user_id, quiz_id)
        return self.quizzes.delete(quiz_id, user_id)

    def _serialize_quiz(self, quiz: Dict[str, Any], *, include_answers: bool) -> Dict[str, Any]:
        questions = []
        for question in quiz.get("questions", []):
            item = {
                "question_id": question.get("question_id"),
                "type": question.get("type", "mcq"),
                "question": question.get("question", ""),
                "options": question.get("options", []),
                "difficulty": question.get("difficulty", "medium"),
                "topic": question.get("topic", ""),
                "source": question.get("source", {}),
            }
            if include_answers:
                item["correct_answer"] = question.get("correct_answer", "")
                item["explanation"] = question.get("explanation", "")
            questions.append(item)
        return {
            "id": str(quiz.get("_id")),
            "title": quiz.get("title", ""),
            "topic": quiz.get("topic", ""),
            "document_ids": quiz.get("document_ids", []),
            "generation_method": quiz.get("generation_method", ""),
            "question_count": len(questions),
            "questions": questions,
            "created_at": quiz.get("created_at"),
        }
def get_quiz_service(settings: Optional[Settings] = None) -> QuizService:
    """Convenience factory used by the study routes."""
    return QuizService(settings)
