"""
RAG chat service — grounded answers over the user's own documents (brief §7, §8).

Pipeline per question:

    question → query embedding → hybrid retrieval → context assembly
             → local Ollama model → answer with [n] citations → sources

Behaviour rules enforced here (brief §7/§22):

* the model is *instructed* to say "I could not find this in your uploaded
  documents." when the context does not contain the answer,
* if retrieval finds nothing at all, that exact message is returned **without
  calling the model**, so an unavailable LLM still gives a useful reply,
* every answer carries the sources (document + page) it was built from, and the
  UI can always tell RAG answers from General-AI answers (``based_on_documents``).

Chat modes (brief §8) are implemented as *retrieval filters*:
``knowledge`` (all documents), ``document`` (one), ``subject`` (a subject),
``selected`` (a list), ``general`` (no retrieval, clearly labelled).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from config.settings import Settings, get_settings
from db.repositories import DocumentRepository
from db.study_repositories import ChatRepository, StudyEventRepository
from models.study import CHAT_MODES
from services.llm import prompts
from services.llm.base import LLMMessage
from services.llm.factory import get_llm_service
from services.search_service import SearchService, SearchResult
from utils.errors import ValidationError
from utils.logging_setup import get_logger
from utils.text import truncate

logger = get_logger(__name__)

NOT_FOUND_MESSAGE = "I could not find this in your uploaded documents."

#: Characters of chunk text kept per context block (small models answer better
#: with focused excerpts than with whole pages).
CONTEXT_BLOCK_CHARS = 1200


@dataclass
class RagAnswer:
    """Everything the chat route needs to render one assistant turn."""

    question: str
    answer: str
    mode: str
    sources: List[Dict[str, Any]] = field(default_factory=list)
    session_id: Optional[str] = None
    model: str = ""
    based_on_documents: bool = True
    retrieval: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "mode": self.mode,
            "sources": self.sources,
            "session_id": self.session_id,
            "model": self.model,
            "based_on_documents": self.based_on_documents,
            "retrieval": self.retrieval,
        }


class RagService:
    """Grounded question answering over the user's documents."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        search_service: Optional[SearchService] = None,
        llm_service=None,
        chats: Optional[ChatRepository] = None,
        documents: Optional[DocumentRepository] = None,
        events: Optional[StudyEventRepository] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.search = search_service or SearchService(self.settings)
        self._llm = llm_service
        self.chats = chats or ChatRepository()
        self.documents = documents or DocumentRepository()
        self.events = events or StudyEventRepository()
        self._last_session_id: Optional[str] = None

    @property
    def llm(self):
        """LLM access is lazy so a missing Ollama only affects answering."""
        if self._llm is None:
            self._llm = get_llm_service(self.settings)
        return self._llm

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def ask(
        self,
        user_id: Any,
        question: str,
        *,
        mode: str = "knowledge",
        document_ids: Optional[List[Any]] = None,
        subject: Optional[str] = None,
        session_id: Optional[Any] = None,
        top_k: Optional[int] = None,
        save: bool = True,
    ) -> RagAnswer:
        """Answer one question using the requested chat mode."""
        question = (question or "").strip()
        if not question:
            raise ValidationError("Please type a question.")
        if mode not in CHAT_MODES:
            raise ValidationError(
                f"Unknown chat mode '{mode}'.",
                hint=f"Supported modes: {', '.join(CHAT_MODES)}.",
            )

        if mode == "general":
            answer = self._answer_general(question, session_id, save)
            self._record_event(user_id, question, mode, based_on_documents=False)
            return answer

        # --- retrieval ----------------------------------------------------
        hits = self.search.search(
            user_id,
            question,
            mode="hybrid",
            document_ids=document_ids or None,
            subject=subject,
            top_k=top_k,
        )
        self._record_event(user_id, question, mode, based_on_documents=bool(hits))

        if not hits:
            # Honest, useful, and no LLM call needed for an empty knowledge base.
            session = self._persist_session(user_id, session_id, question, mode, save=False)
            return RagAnswer(
                question=question,
                answer=(
                    f"{NOT_FOUND_MESSAGE}\n\n"
                    "Upload or process a document that covers this topic, then ask again."
                ),
                mode=mode,
                sources=[],
                session_id=session,
                model=self.settings.llm_model,
                based_on_documents=False,
                retrieval={"hits": 0, "reason": "no_matching_chunks"},
            )

        blocks, sources = self._build_context(hits)
        answer_text, model_used = self._compose_answer(question, blocks, session_id, save)
        return RagAnswer(
            question=question,
            answer=answer_text,
            mode=mode,
            sources=self._annotate_citations(answer_text, sources),
            session_id=self._last_session_id,
            model=model_used,
            based_on_documents=True,
            retrieval={
                "hits": len(hits),
                "context_chars": sum(len(block["text"]) for block in blocks),
                "top_score": hits[0].score,
            },
        )

    # ------------------------------------------------------------------
    # Answering helpers
    # ------------------------------------------------------------------
    def _answer_general(self, question: str, session_id: Optional[Any], save: bool) -> RagAnswer:
        """General AI mode: no retrieval, clearly labelled (brief §8)."""
        history = self._history(session_id) if session_id else []
        messages = history + [LLMMessage(role="user", content=question)]
        response = self.llm.chat(messages, system=prompts.GENERAL_SYSTEM)
        self._last_session_id = self._persist_session(None, session_id, question, "general", save)
        if save and self._last_session_id:
            self._save_turn(self._last_session_id, question, response.text, mode="general")
        return RagAnswer(
            question=question,
            answer=response.text or "The local model returned an empty answer. Please try again.",
            mode="general",
            sources=[],
            session_id=self._last_session_id,
            model=response.model or self.settings.llm_model,
            based_on_documents=False,
            retrieval={"mode": "general"},
        )

    def _build_context(self, hits: List[SearchResult]) -> tuple:
        """Assemble numbered context blocks within the configured char budget."""
        budget = self.settings.rag_max_context_chars
        blocks: List[Dict[str, Any]] = []
        sources: List[Dict[str, Any]] = []
        used = 0
        for index, hit in enumerate(hits, start=1):
            text = truncate(hit.text, CONTEXT_BLOCK_CHARS)
            if used + len(text) > budget and blocks:
                break
            used += len(text)
            blocks.append(
                {
                    "index": index,
                    "title": hit.document_title or "Untitled document",
                    "page": hit.page_number,
                    "text": text,
                }
            )
            sources.append(
                {
                    "index": index,
                    "document_id": hit.document_id,
                    "title": hit.document_title or "Untitled document",
                    "page_number": hit.page_number,
                    "chunk_id": hit.chunk_id,
                    "snippet": (hit.text or "")[:280],
                    "score": hit.score,
                    "source_type": hit.source_type,
                }
            )
        return blocks, sources

    def _compose_answer(
        self, question: str, blocks: List[Dict[str, Any]], session_id: Optional[Any], save: bool
    ) -> tuple:
        """Call the local model with the grounded prompt and persist the turn."""
        prompt = prompts.build_rag_user_prompt(question, blocks)
        response = self.llm.generate(
            prompt, system=prompts.RAG_SYSTEM, max_tokens=self.settings.llm_max_tokens
        )
        answer = response.text.strip() or (
            "The local model returned an empty answer. Please try rephrasing the question."
        )
        self._last_session_id = self._persist_session(None, session_id, question, "knowledge", save)
        if save and self._last_session_id:
            self._save_turn(self._last_session_id, question, answer, mode="knowledge")
        return answer, response.model or self.settings.llm_model

    @staticmethod
    def _annotate_citations(answer: str, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Mark which sources the answer actually cited as ``[n]``."""
        cited = {index for index in range(1, len(sources) + 1) if f"[{index}]" in answer}
        for index, source in enumerate(sources, start=1):
            source["cited"] = index in cited
        # Cited sources first so the UI can highlight what the answer used.
        return sorted(sources, key=lambda item: (not item["cited"], item["index"]))

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------
    def _history(self, session_id: Optional[Any]) -> List[LLMMessage]:
        """Recent turns of this conversation, oldest first."""
        if not session_id:
            return []
        try:
            rows = self.chats.recent_messages(session_id, limit=self.settings.rag_history_turns * 2)
        except Exception as exc:  # noqa: BLE001 - history is best-effort
            logger.warning("Could not load chat history: %s", exc)
            return []
        return [
            LLMMessage(role=str(row.get("role", "user")), content=str(row.get("content", "")))
            for row in rows
            if row.get("role") in ("user", "assistant")
        ]

    def _persist_session(
        self, user_id: Optional[Any], session_id: Optional[Any], question: str, mode: str, save: bool
    ) -> Optional[str]:
        """Return the session id to use, creating one when needed."""
        if not save:
            return None
        if session_id and user_id:
            existing = self.chats.get_session(session_id, user_id)
            if existing:
                return str(existing["_id"])
        if not user_id:
            return None
        try:
            new_id = self.chats.create_session(
                {
                    "user_id": str(user_id),
                    "title": truncate(question, 60, suffix="…"),
                    "mode": mode,
                    "message_count": 0,
                }
            )
            return str(new_id)
        except Exception as exc:  # noqa: BLE001 - chat must work even without storage
            logger.warning("Could not create chat session: %s", exc)
            return None

    def _save_turn(self, session_id: str, question: str, answer: str, *, mode: str) -> None:
        """Store the user question and the assistant answer for the session."""
        try:
            self.chats.add_message(
                {"session_id": session_id, "role": "user", "content": question, "mode": mode,
                 "sources": []}
            )
            self.chats.add_message(
                {"session_id": session_id, "role": "assistant", "content": answer, "mode": mode,
                 "sources": []}
            )
            self.chats.touch_session(session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not persist chat turn: %s", exc)

    def _record_event(self, user_id: Any, question: str, mode: str, *, based_on_documents: bool) -> None:
        """Log the question so 'frequently searched topics' stays data-driven."""
        try:
            self.events.create(
                {
                    "user_id": str(user_id),
                    "event_type": "chat_question",
                    "topic": "",
                    "payload": {
                        "question": truncate(question, 200),
                        "mode": mode,
                        "based_on_documents": based_on_documents,
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record chat event: %s", exc)


def get_rag_service(settings: Optional[Settings] = None) -> RagService:
    """Convenience factory used by the chat routes."""
    return RagService(settings)