"""
Flashcard service (brief §10).

Generation strategy — LLM first, deterministic fallback always available:

1. **LLM path**: the local model writes question/answer pairs *from the retrieved
   excerpts* (the prompt forbids outside knowledge) and names the excerpt it used,
   so every card keeps a real source (document + page).
2. **Extractive path** (no model needed): definition sentences become "What is X?"
   cards and key sentences become cloze cards. Deterministic and honestly labelled
   ``generation_method="extractive"``.

Cards can be edited, deleted and reviewed; each review outcome is stored and feeds
knowledge-gap detection (brief §11).
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence

from config.settings import Settings, get_settings
from db.repositories import DocumentRepository, PageRepository
from db.study_repositories import FlashcardRepository, StudyEventRepository
from models.domain import utcnow
from models.study import DIFFICULTIES
from services.llm import prompts
from services.llm.factory import get_llm_service
from services.search_service import SearchService
from utils.errors import NotFoundError, ValidationError
from utils.logging_setup import get_logger
from utils.text import (STOPWORDS, is_meaningful_text, keyword_scores, split_sentences, truncate)

logger = get_logger(__name__)

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-']{2,}")

#: "X is a/are the ..." sentences — used to build definition cards.
_DEFINITION_RE = re.compile(
    r"^(?P<term>[A-Za-z][\w\s\-']{2,50}?)\s+(?:is|are|means)\s+(?P<body>.{20,400})$",
    re.IGNORECASE,
)

#: Excerpts retrieved per generation call (keeps prompts small).
MAX_EXCERPTS = 8


class FlashcardService:
    """Create and manage revision flashcards."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        cards: Optional[FlashcardRepository] = None,
        documents: Optional[DocumentRepository] = None,
        pages: Optional[PageRepository] = None,
        search: Optional[SearchService] = None,
        events: Optional[StudyEventRepository] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.cards = cards or FlashcardRepository()
        self.documents = documents or DocumentRepository()
        self.pages = pages or PageRepository()
        self.search = search or SearchService(self.settings)
        self.events = events or StudyEventRepository()

    def _llm_available(self) -> bool:
        try:
            llm = get_llm_service(self.settings)
            return llm.is_available()
        except Exception:  # noqa: BLE001 - generation must work without the model
            return False

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    def generate(
        self,
        user_id: Any,
        *,
        document_ids: Sequence[Any],
        topic: str = "",
        count: int = 8,
    ) -> Dict[str, Any]:
        """Generate flashcards from the selected documents (LLM → extractive)."""
        user_id = str(user_id)
        count = max(1, min(30, int(count or 8)))
        document_ids = [str(item) for item in document_ids or []]
        if not document_ids:
            raise ValidationError(
                "Select at least one document to generate flashcards from.",
                code="no_documents_selected",
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
                code="no_text_for_cards",
            )

        cards: List[Dict[str, Any]] = []
        method = "extractive"
        if self._llm_available():
            cards = self._generate_with_llm(topic, excerpts, count)
            if cards:
                method = "llm"
        if len(cards) < count:
            cards.extend(self._generate_extractive(excerpts, count - len(cards), used=cards))

        if not cards:
            raise ValidationError(
                "Flashcards could not be generated from this material.",
                code="no_cards_generated",
                hint="The text may be too short or too repetitive — try another document.",
            )

        created = []
        for card in cards[:count]:
            source_index = int(card.get("source_index", 1) or 1)
            excerpt = excerpts[source_index - 1] if 0 < source_index <= len(excerpts) else excerpts[0]
            question = truncate(str(card.get("question", "")), 400)
            answer = truncate(str(card.get("answer", "")), 800)
            if not question or not answer:
                continue
            created.append(
                {
                    "user_id": user_id,
                    "question": question,
                    "answer": answer,
                    "topic": truncate(str(card.get("topic", "") or topic), 120),
                    "difficulty": card.get("difficulty")
                    if card.get("difficulty") in DIFFICULTIES
                    else "medium",
                    "document_ids": [excerpt["document_id"]],
                    "source": {
                        "document_id": excerpt["document_id"],
                        "title": title_map.get(excerpt["document_id"], excerpt["title"]),
                        "page_number": excerpt["page_number"],
                    },
                    "generation_method": method,
                    "review_status": "new",
                    "review_count": 0,
                }
            )

        inserted = self.cards.create_many(created)
        logger.info("Generated %s flashcards (%s) for user %s", inserted, method, user_id)
        return {
            "created": inserted,
            "method": method,
            "topic": topic,
            "documents": [
                {"document_id": document_id, "title": title_map.get(document_id, "")}
                for document_id in document_ids
            ],
        }

    # ------------------------------------------------------------------
    # Generation internals
    # ------------------------------------------------------------------
    def _collect_excerpts(
        self, user_id: str, document_ids: Sequence[str], topic: str
    ) -> List[Dict[str, Any]]:
        """
        Gather the passages flashcards will be built from.

        A topic turns generation into targeted retrieval (only relevant pages);
        without a topic the first pages of every selected document are used, which
        keeps generation fast and predictable.
        """
        excerpts: List[Dict[str, Any]] = []
        seen_pages: set = set()
        title_map: Dict[str, str] = {}

        if topic.strip():
            for hit in self.search.search(
                user_id, topic, mode="hybrid", document_ids=list(document_ids), top_k=MAX_EXCERPTS
            ):
                key = (hit.document_id, hit.page_number)
                if key in seen_pages or not is_meaningful_text(hit.text, 80):
                    continue
                seen_pages.add(key)
                title_map.setdefault(hit.document_id, hit.document_title)
                excerpts.append(
                    {
                        "document_id": hit.document_id,
                        "title": hit.document_title,
                        "page_number": hit.page_number,
                        "text": hit.text,
                    }
                )

        if len(excerpts) < MAX_EXCERPTS:
            for document_id in document_ids:
                for page in self.pages.list_for_document(document_id):
                    key = (document_id, page.get("page_number"))
                    if key in seen_pages or not is_meaningful_text(page.get("text", ""), 80):
                        continue
                    seen_pages.add(key)
                    excerpts.append(
                        {
                            "document_id": document_id,
                            "title": title_map.get(document_id, ""),
                            "page_number": page.get("page_number"),
                            "text": page.get("text", ""),
                        }
                    )
                    if len(excerpts) >= MAX_EXCERPTS:
                        return excerpts
        return excerpts

    def _generate_with_llm(
        self, topic: str, excerpts: Sequence[Dict[str, Any]], count: int
    ) -> List[Dict[str, Any]]:
        """Ask the local model for cards grounded in the given excerpts."""
        try:
            llm = get_llm_service(self.settings)
            payload = llm.generate_json(
                prompts.build_flashcard_prompt(topic, list(excerpts), count),
                system=prompts.FLASHCARD_SYSTEM,
                max_tokens=1200,
            )
        except Exception as exc:  # noqa: BLE001 - fall back to extractive generation
            logger.warning("LLM flashcard generation failed: %s", exc)
            return []
        if not payload:
            return []

        cards: List[Dict[str, Any]] = []
        for item in payload.get("flashcards", []) or []:
            if not isinstance(item, dict):
                continue
            question = str(item.get("question", "")).strip()
            answer = str(item.get("answer", "")).strip()
            if not question or not answer:
                continue
            cards.append(
                {
                    "question": question,
                    "answer": answer,
                    "topic": str(item.get("topic", "")).strip(),
                    "difficulty": str(item.get("difficulty", "medium")).strip().lower(),
                    "source_index": item.get("source_excerpt", 1),
                }
            )
        return cards

    @staticmethod
    def _important_term(sentence: str, repeats: int = 0) -> str:
        """Pick the *important term* of a sentence to blank out.

        Candidates are key *phrases* extracted the same way the knowledge-graph
        extractor finds concepts — capitalised phrases, acronyms and frequent
        nominal terms — because those are exactly the notions a flashcard should
        test. Ranking combines:

        * phrase length (multi-word phrases describe the driving idea),
        * acronym bonus (BCNF, TCP, DBMS),
        * repetition across the document (`repeats`),
        * position bias (the sentence subject — what the sentence is *about*).

        Verbs, adjectives, single letters and glue words can never win: they are
        not phrase candidates. Falls back to the strongest single nominal word
        when no phrase exists.
        """
        import re as _re

        candidates: dict = {}
        lowered_sentence = (sentence or "").lower()
        words = _re.findall(r"[A-Za-z][A-Za-z\-']{2,}", lowered_sentence)

        boundary = {
            # light verbs / copulas
            "is", "are", "was", "were", "be", "been", "being", "has", "have",
            "had", "does", "did", "do", "can", "could", "will", "would", "shall",
            "should", "may", "might", "must", "means", "mean", "refers", "called",
            "known", "uses", "use", "using", "used", "requires", "require",
            "needs", "need", "process", "carried", "carries", "carry", "makes",
            "make", "made", "takes", "take",
            # determiners / pronouns / connectors / prepositions
            "a", "an", "the", "it", "its", "this", "that", "these", "those",
            "and", "or", "but", "so", "as", "at", "by", "for", "from", "in",
            "into", "of", "on", "out", "through", "to", "with", "without",
            "each", "every", "such", "than", "then", "there", "here", "when",
            "while", "which", "what", "who", "whom", "whose", "where", "how",
        }

        def ok_edges(tokens: list) -> bool:
            return bool(tokens) and tokens[0] not in boundary and tokens[-1] not in boundary

        def add(phrase: str, base: float) -> None:
            phrase = " ".join(phrase.split())
            if not phrase or phrase in STOPWORDS:
                return
            if not ok_edges(phrase.split()):
                return
            candidates[phrase] = candidates.get(phrase, 0.0) + base

        # 1. Capitalised phrases: "Functional Dependency", "Candidate Key".
        for match in _re.finditer(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b", sentence or ""):
            phrase = match.group(0)
            if len(phrase) <= 4 or phrase.lower() in STOPWORDS:
                continue
            score = 3.0 + len(phrase.split())          # length bonus first
            if match.start() < 40:
                score += 1.5                            # sentence subject bias
            add(phrase, score)

        # 2. Acronyms and alphanumeric terms: BCNF, TCP, 3NF.
        for match in _re.finditer(r"\b(?:[A-Z]{2,6}|\d[A-Z]{1,4})\b", sentence or ""):
            score = 3.5
            head = (sentence or "")[:match.start()].strip()
            if not head or re.search(r"[.!?]\s*$", head):  # noqa: F821 - see note
                score += 2.0                     # starts the sentence: the subject
            add(match.group(0).lower(), score)

        # 3. Frequent nominal terms: multi-word runs of non-stopword tokens.
        nominal_runs: list = []
        run: list = []
        for word in words:
            if word not in STOPWORDS and len(word) > 2 and not word.isdigit():
                run.append(word)
            else:
                if len(run) >= 2:
                    nominal_runs.append(run)
                run = []
        if len(run) >= 2:
            nominal_runs.append(run)
        for run in nominal_runs:
            for size in (3, 2):
                for i in range(len(run) - size + 1):
                    phrase = " ".join(run[i:i + size])
                    if len(phrase) < 5:
                        continue
                    add(phrase, 1.5 + size * 0.75 + (1.5 if sentence.find(phrase) < 40 else 0.0))

        # 3b. Single capitalised subject words: "Normalization is the process of…"
        #     — a lone sentence-initial capitalised term IS the subject even
        #     without a second capitalised word beside it.
        first = words[0] if words else ""
        if first and len(first) > 3 and first not in STOPWORDS:
            add(first, 2.0)

        # 4. Document-wide repetition strengthens a candidate.
        if repeats:
            for phrase in list(candidates):
                candidates[phrase] += min(2.0, 0.5 * repeats)

        if candidates:
            # Subject bias: the first meaningful word of the sentence is what the
            # sentence is about, so prefer candidates containing it.
            if first and first not in STOPWORDS:
                subject = max(
                    candidates.items(),
                    key=lambda item: (first in item[0].lower().split(), item[1]),
                )
                if first in subject[0].lower().split():
                    return subject[0]
            return max(candidates, key=candidates.get)

        # Fallback: strongest single nominal word, never glue or filler.
        tokens = keyword_scores(sentence, top_n=60)
        for word, _count in tokens:
            if len(word) > 3 and word not in STOPWORDS:
                return word
        return ""

    def _generate_extractive(
        self,
        excerpts: Sequence[Dict[str, Any]],
        count: int,
        *,
        used: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Deterministic cards when the model is unavailable.

        Definition sentences become "What is X?" cards; other informative sentences
        become cloze (fill-the-blank) cards. Nothing is generated from text too
        short to be meaningful, so no empty cards are created.
        """
        from utils.text import clean_concept_label

        existing_questions = {str(item.get("question", "")).lower() for item in used}
        cards: List[Dict[str, Any]] = []

        for index, excerpt in enumerate(excerpts, start=1):
            if len(cards) >= count:
                break
            for sentence in split_sentences(excerpt.get("text", "")):
                if len(cards) >= count:
                    break
                if not is_meaningful_text(sentence, 60) or len(sentence) > 400:
                    continue

                question = ""
                answer = ""
                match = _DEFINITION_RE.match(sentence.strip())
                if match:
                    term = clean_concept_label(match.group("term"))
                    body = match.group("body").strip().rstrip(".")
                    if term and len(term.split()) <= 6:
                        question = f"What is {term}?"
                        answer = truncate(body, 400)
                else:
                    target = self._important_term(sentence)
                    if target and target in sentence:
                        blanked = sentence.replace(target, "_____", 1)
                        # Drop a leading heading line that names the answer
                        # (e.g. a section title "Functional Dependency" right
                        # before the sentence that defines it), otherwise the
                        # question would give the answer away.
                        kept_lines = [
                            line for line in blanked.split("\n")
                            if line.strip().lower() != target.lower()
                            and not (
                                len(line.strip()) <= 60
                                and line.strip().lower().startswith(target.lower())
                                and "_____" not in line
                            )
                        ]
                        blanked = "\n".join(kept_lines).strip() or blanked
                        question = f"Fill in the blank: {truncate(blanked, 300)}"
                        answer = target

                if not question or question.lower() in existing_questions:
                    continue
                existing_questions.add(question.lower())
                cards.append(
                    {
                        "question": question,
                        "answer": answer,
                        "topic": excerpt.get("title", ""),
                        "difficulty": "medium",
                        "source_index": index,
                    }
                )
        return cards

    # ------------------------------------------------------------------
    # CRUD + review
    # ------------------------------------------------------------------
    def list_cards(
        self,
        user_id: Any,
        *,
        document_ids: Optional[List[Any]] = None,
        topic: Optional[str] = None,
        review_status: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        cards, total, page, page_size = self.cards.list_for_user(
            user_id,
            document_ids=document_ids,
            topic=topic,
            review_status=review_status,
            page=page,
            page_size=page_size,
        )
        return {
            "cards": [self._serialize(card) for card in cards],
            "total": total,
            "page": page,
            "page_size": page_size,
            "topic_summary": self.cards.topic_summary(user_id),
        }

    def get_card(self, user_id: Any, card_id: Any) -> Dict[str, Any]:
        card = self.cards.get(card_id, user_id)
        if not card:
            raise NotFoundError("Flashcard not found.", code="flashcard_not_found")
        return card

    def update_card(self, user_id: Any, card_id: Any, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Edit a card's text/topic/difficulty (never its source)."""
        self.get_card(user_id, card_id)
        payload: Dict[str, Any] = {}
        if fields.get("question"):
            payload["question"] = truncate(str(fields["question"]), 400)
        if fields.get("answer"):
            payload["answer"] = truncate(str(fields["answer"]), 800)
        if fields.get("topic") is not None:
            payload["topic"] = truncate(str(fields["topic"]), 120)
        if fields.get("difficulty") in DIFFICULTIES:
            payload["difficulty"] = fields["difficulty"]
        if payload:
            self.cards.update(card_id, user_id, payload)
        return self.get_card(user_id, card_id)

    def review_card(self, user_id: Any, card_id: Any, outcome: str) -> Dict[str, Any]:
        """
        Record a review outcome (``easy`` / ``medium`` / ``hard``).

        The next due date uses a simple, explainable spaced-repetition rule
        (1 / 3 / 7 days) — no hidden "AI schedule".
        """
        if outcome not in DIFFICULTIES:
            raise ValidationError("Review outcome must be easy, medium or hard.")
        self.get_card(user_id, card_id)
        delays = {"easy": 7, "medium": 3, "hard": 1}
        next_due = utcnow() + timedelta(days=delays[outcome])
        self.cards.record_review(card_id, user_id, status=outcome, next_due=next_due)
        try:
            card = self.get_card(user_id, card_id)
            self.events.create(
                {
                    "user_id": str(user_id),
                    "event_type": "flashcard_review",
                    "topic": card.get("topic", ""),
                    "document_ids": [str(item) for item in card.get("document_ids", [])],
                    "correct": outcome == "easy",
                    "payload": {"outcome": outcome, "card_id": str(card_id)},
                }
            )
        except Exception as exc:  # noqa: BLE001 - analytics logging is best-effort
            logger.warning("Could not record flashcard review: %s", exc)
        return self.get_card(user_id, card_id)

    def delete_card(self, user_id: Any, card_id: Any) -> bool:
        self.get_card(user_id, card_id)
        return self.cards.delete(card_id, user_id)

    @staticmethod
    def _serialize(card: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(card.get("_id")),
            "question": card.get("question", ""),
            "answer": card.get("answer", ""),
            "topic": card.get("topic", ""),
            "difficulty": card.get("difficulty", "medium"),
            "review_status": card.get("review_status", "new"),
            "review_count": card.get("review_count", 0),
            "last_reviewed_at": card.get("last_reviewed_at"),
            "due_at": card.get("due_at"),
            "generation_method": card.get("generation_method", ""),
            "source": card.get("source", {}),
            "document_ids": card.get("document_ids", []),
            "created_at": card.get("created_at"),
        }


def get_flashcard_service(settings: Optional[Settings] = None) -> FlashcardService:
    """Convenience factory used by the study routes."""
    return FlashcardService(settings)
