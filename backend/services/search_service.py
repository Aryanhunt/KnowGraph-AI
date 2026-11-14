"""
Search service — hybrid semantic + keyword retrieval (brief §6, §15).

The public method is :meth:`SearchService.search`, which:

1. embeds the query with the *same* embedding model used to index the chunks
   (so similarity numbers are comparable),
2. runs a vector (semantic) search,
3. runs a keyword search using MongoDB's text index,
4. merges the two ranked lists with **Reciprocal Rank Fusion** — a real,
   well-known ranking technique, not a fabricated "AI score" (brief §15).

The ``score`` returned to the UI is therefore either a cosine similarity (single
mode) or an RRF score (hybrid), both derived from the retrieval system itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from config.settings import Settings, get_settings
from db.repositories import ChunkRepository, DocumentRepository
from db.study_repositories import SearchLogRepository
from services.embeddings.factory import get_embedding_service
from services.vector.factory import get_vector_store
from utils.errors import LocalServiceUnavailableError
from utils.logging_setup import get_logger

logger = get_logger(__name__)

RANK_FUSION_K = 60      # standard RRF constant (the "magic 60").


@dataclass
class SearchResult:
    """One retrieval result, ready to be cited in the UI."""

    document_id: str
    document_title: str
    page_number: Optional[int]
    chunk_id: str
    text: str
    source_type: str           # semantic | keyword | hybrid
    score: Optional[float] = None
    metadata: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "document_title": self.document_title,
            "page_number": self.page_number,
            "chunk_id": self.chunk_id,
            "snippet": (self.text or "")[:300],
            "source_type": self.source_type,
            "score": self.score,
            "metadata": self.metadata or {},
        }


class SearchService:
    """Hybrid retriever used by global search and the RAG pipeline."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        documents: Optional[DocumentRepository] = None,
        chunks: Optional[ChunkRepository] = None,
        logs: Optional[SearchLogRepository] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.documents = documents or DocumentRepository()
        self.chunks = chunks or ChunkRepository()
        self.logs = logs or SearchLogRepository()

    # ------------------------------------------------------------------
    # Query embedding (shared by search and RAG)
    # ------------------------------------------------------------------
    def _embed_query(self, user_id: str, query: str) -> Optional[List[float]]:
        """Embed a query; return None when embeddings are unavailable."""
        if not query.strip():
            return None
        try:
            service = get_embedding_service(self.settings)
            if not service.is_available():
                logger.info("Embedding model unavailable — falling back to keyword search")
                return None
            return service.embed_query(query)
        except LocalServiceUnavailableError as exc:
            logger.warning("Query embedding failed: %s", exc.message)
            return None

    # ------------------------------------------------------------------
    # Public search API
    # ------------------------------------------------------------------
    def search(
        self,
        user_id: Any,
        query: str,
        *,
        mode: str = "hybrid",
        document_ids: Optional[List[Any]] = None,
        subject: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> List[SearchResult]:
        """
        Return ranked results across the user's *ready* documents.

        ``mode`` selects semantic, keyword or hybrid retrieval (brief §8/§15).
        ``document_ids``/``subject`` restrict the search (chat modes).
        """
        user_id = str(user_id)
        query = (query or "").strip()
        top_k = top_k or self.settings.rag_top_k
        if not query:
            return []

        doc_ids, title_map = self._resolve_scope(user_id, document_ids, subject)

        # Keyword half runs for every mode so pure-keyword and hybrid both work.
        keyword_rows = self.chunks.keyword_search(
            user_id, query, limit=top_k * 3, document_ids=doc_ids
        )

        if mode == "semantic" or (mode == "hybrid" and self.settings.hybrid_search):
            vector_hits = self._vector_search(user_id, query, top_k, doc_ids, mode)
            if vector_hits:
                return self._merge(vector_hits, keyword_rows, top_k, title_map, mode)

        # Keyword-only fallback (no embedding model, or pure keyword mode).
        results = [
            self._row_to_result(row, title_map, "keyword", float(row.get("keyword_score", 0.0)))
            for row in keyword_rows[:top_k]
        ]
        self._log(user_id, query, mode, document_ids, subject, len(results))
        return results

    def search_pages(
        self,
        user_id: Any,
        query: str,
        *,
        document_ids: Optional[List[Any]] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Page-level keyword search — powers "search within a document/page" (§15)."""
        if not query.strip():
            return []
        pages = self._pages_search(user_id, query, document_ids=document_ids, limit=limit)
        self._log(user_id, query, "page", document_ids, None, len(pages))
        return pages

    # ------------------------------------------------------------------
    # Vector + merge helpers
    # ------------------------------------------------------------------
    def _vector_search(
        self,
        user_id: str,
        query: str,
        top_k: int,
        document_ids: Optional[List[str]],
        mode: str,
    ) -> List[SearchResult]:
        query_vector = self._embed_query(user_id, query)
        if query_vector is None:
            return []
        try:
            store = get_vector_store(self.settings)
        except Exception as exc:  # noqa: BLE001 - vector db down → keyword only
            logger.warning("Vector store unavailable during search: %s", exc)
            return []
        result = store.search(
            query_vector, top_k=top_k * 3, user_id=user_id, document_ids=document_ids
        )
        if not result.ok:
            return []
        hits: List[SearchResult] = []
        for hit in result.hits:
            metadata = hit.metadata or {}
            document_id = str(metadata.get("document_id", ""))
            hits.append(
                SearchResult(
                    document_id=document_id,
                    document_title=metadata.get("title", ""),
                    page_number=hit.page_number,
                    chunk_id=hit.chunk_id,
                    text=hit.text,
                    source_type="semantic",
                    score=hit.score,
                    metadata=metadata,
                )
            )
        return hits

# ------------------------------------------------------------------
    # Row building + merging
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_result(
        row: Dict[str, Any], title_map: Dict[str, str], source_type: str, score: Optional[float]
    ) -> SearchResult:
        document_id = str(row.get("document_id", ""))
        page_number = row.get("page_number")
        try:
            page_number = int(page_number) if page_number is not None else None
        except (TypeError, ValueError):
            page_number = None
        metadata = row.get("metadata", {}) if isinstance(row.get("metadata"), dict) else {}
        return SearchResult(
            document_id=document_id,
            document_title=title_map.get(document_id, ""),
            page_number=page_number,
            chunk_id=str(row.get("_id", "")),
            text=row.get("text", ""),
            source_type=source_type,
            score=score,
            metadata={
                "chunk_index": row.get("chunk_index"),
                "section_title": metadata.get("section_title", ""),
            },
        )

    def _merge(
        self,
        vector_hits: List[SearchResult],
        keyword_rows: List[Dict[str, Any]],
        top_k: int,
        title_map: Dict[str, str],
        mode: str,
    ) -> List[SearchResult]:
        """Reciprocal Rank Fusion of the two ranked lists."""
        by_id: Dict[str, SearchResult] = {}
        rrf: Dict[str, float] = {}

        def rank_list(hits: List[SearchResult]) -> None:
            for rank, hit in enumerate(hits):
                by_id[hit.chunk_id] = hit
                rrf[hit.chunk_id] = rrf.get(hit.chunk_id, 0.0) + 1.0 / (RANK_FUSION_K + rank)

        rank_list(vector_hits)

        keyword_hits = [
            self._row_to_result(row, title_map, "keyword", float(row.get("keyword_score", 0.0)))
            for row in keyword_rows
        ]
        for rank, hit in enumerate(keyword_hits):
            if hit.chunk_id not in by_id:
                by_id[hit.chunk_id] = hit
            rrf[hit.chunk_id] = rrf.get(hit.chunk_id, 0.0) + 1.0 / (RANK_FUSION_K + rank)

        ordered = sorted(rrf, key=rrf.get, reverse=True)
        results = [by_id[identifier] for identifier in ordered if identifier in by_id][:top_k]
        for hit in results:
            hit.score = round(rrf.get(hit.chunk_id, 0.0), 4)
            hit.source_type = "hybrid"
        return results

    # ------------------------------------------------------------------
    # Scope + logging helpers
    # ------------------------------------------------------------------
    def _resolve_scope(
        self, user_id: str, document_ids: Optional[List[Any]], subject: Optional[str]
    ) -> Tuple[Optional[List[str]], Dict[str, str]]:
        """Return ``(doc_ids or None, title_map)`` for the chat-mode filters."""
        ready = self.documents.list_all_for_user(
            user_id, only_ready=True, subject=subject, document_ids=document_ids
        )
        ids = [str(row["_id"]) for row in ready]
        title_map = self.documents.find_titles_for_user(user_id, ids) if ids else {}
        return ids if ids else None, title_map

    def _pages_search(self, user_id, query, *, document_ids=None, limit=20):
        from db.repositories import PageRepository

        return PageRepository().search_text(user_id, query, limit=limit, document_ids=document_ids)

    def _log(self, user_id, query, mode, document_ids, subject, result_count) -> None:
        try:
            self.logs.create(
                {
                    "user_id": str(user_id),
                    "query": query,
                    "mode": mode,
                    "filters": {"document_ids": document_ids, "subject": subject},
                    "result_count": result_count,
                }
            )
        except Exception as exc:  # noqa: BLE001 - search logging is best-effort
            logger.warning("Could not log search '%s': %s", query, exc)


def get_search_service(settings: Optional[Settings] = None) -> SearchService:
    return SearchService(settings)