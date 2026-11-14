"""
Domain models for users, documents, pages, chunks and the processing lifecycle.

These dataclasses are the single source of truth for the field names listed in
brief §5. They are deliberately plain ``dataclasses`` (no ODM dependency):
services convert them with :meth:`to_mongo` before writing and hydrate them with
:meth:`from_mongo` after reading.

Fields beyond the brief are commented where they exist for a concrete reason
(progress reporting, duplicate detection, subject filtering, ...).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp — every stored date uses this helper."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Processing lifecycle (drives the progress UI)
# ---------------------------------------------------------------------------
class ProcessingStatus:
    """Document processing states, in pipeline order."""

    QUEUED = "queued"
    EXTRACTING = "extracting_text"
    RUNNING_OCR = "running_ocr"
    CLEANING = "cleaning_text"
    CHUNKING = "creating_chunks"
    EMBEDDING = "generating_embeddings"
    EXTRACTING_TOPICS = "extracting_topics"
    BUILDING_GRAPH = "building_knowledge_graph"
    READY = "completed"
    FAILED = "failed"

    #: Ordered stages with the progress fraction reported to the UI.
    STAGES: Dict[str, float] = {
        QUEUED: 0.05,
        EXTRACTING: 0.25,
        RUNNING_OCR: 0.42,
        CLEANING: 0.50,
        CHUNKING: 0.58,
        EMBEDDING: 0.74,
        EXTRACTING_TOPICS: 0.84,
        BUILDING_GRAPH: 0.92,
        READY: 1.0,
    }

    LABELS: Dict[str, str] = {
        QUEUED: "Uploading...",
        EXTRACTING: "Extracting text...",
        RUNNING_OCR: "Running OCR...",
        CLEANING: "Cleaning text...",
        CHUNKING: "Creating chunks...",
        EMBEDDING: "Generating embeddings...",
        EXTRACTING_TOPICS: "Extracting topics...",
        BUILDING_GRAPH: "Building knowledge graph...",
        READY: "Completed",
        FAILED: "Failed",
    }

    TERMINAL = {READY, FAILED}

    @classmethod
    def progress_for(cls, status: str) -> float:
        return cls.STAGES.get(status, 0.0)

    @classmethod
    def label_for(cls, status: str) -> str:
        return cls.LABELS.get(status, status)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
@dataclass
class User:
    email: str
    full_name: str
    password_hash: str
    _id: Optional[str] = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def to_mongo(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload.pop("_id", None)
        return payload

    @classmethod
    def from_mongo(cls, document: Dict[str, Any]) -> "User":
        data = dict(document)
        data["_id"] = str(data.pop("_id")) if "_id" in data else None
        return cls(**{k: v for k, v in data.items() if k in cls.__annotations__})


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
@dataclass
class Document:
    """One uploaded file and its processing metadata."""

    user_id: str
    title: str
    original_filename: str
    file_path: str
    file_type: str                      # extension without dot: pdf, png, docx, txt, md
    mime_type: str
    file_size: int
    _id: Optional[str] = None
    file_hash: Optional[str] = None     # duplicate detection within a user
    upload_date: datetime = field(default_factory=utcnow)
    processing_status: str = ProcessingStatus.QUEUED
    processing_error: Optional[str] = None
    page_count: int = 0
    chunk_count: int = 0
    ocr_used: bool = False
    ocr_page_count: int = 0
    language: str = "unknown"
    summary: str = ""
    tags: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    subject: str = ""                   # enables "Chat with Subject" (brief §8)
    is_research_paper: bool = False     # enables research paper mode (brief §14)
    char_count: int = 0
    progress: float = 0.0               # 0..1 for the progress bar
    current_stage: str = ProcessingStatus.QUEUED
    embedding_model: str = ""           # which embedding model indexed this document
    summary_method: str = ""            # llm | extractive — the UI stays honest
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    processed_at: Optional[datetime] = None

    def to_mongo(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload.pop("_id", None)
        return payload

    @classmethod
    def from_mongo(cls, document: Dict[str, Any]) -> "Document":
        data = dict(document)
        data["_id"] = str(data.pop("_id")) if "_id" in data else None
        return cls(**{k: v for k, v in data.items() if k in cls.__annotations__})


@dataclass
class DocumentPage:
    """Extracted (or OCR-recognised) text for a single page."""

    document_id: str
    user_id: str
    page_number: int
    text: str
    _id: Optional[str] = None
    ocr_used: bool = False
    ocr_confidence: Optional[float] = None
    image_path: Optional[str] = None    # stored page render, when OCR was needed
    char_count: int = 0
    section_title: str = ""             # used by non-paginated formats (docx/md)
    created_at: datetime = field(default_factory=utcnow)
    # --- OCR quality (brief: quality pipeline) ---------------------------
    quality_label: str = ""             # good | acceptable | needs_review | poor | unreadable
    quality_metrics: Dict[str, Any] = field(default_factory=dict)
    quality_warnings: List[str] = field(default_factory=list)
    ocr_engine: str = ""
    ocr_preprocessing: Dict[str, Any] = field(default_factory=dict)
    ocr_run_at: Optional[datetime] = None
    # --- OCR correction / review ------------------------------------------
    original_text: str = ""             # untouched OCR/digital output (audit)
    corrected_text: str = ""            # user-entered correction (preferred)
    correction_status: str = ""         # corrected | reviewed | ""
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    correction_version: int = 0         # bumped on every saved correction
    needs_reindex: bool = False         # set when a correction is pending re-index

    def to_mongo(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload.pop("_id", None)
        return payload


@dataclass
class DocumentChunk:
    """A chunk of page text that was embedded and stored in the vector database."""

    document_id: str
    user_id: str
    page_number: int
    chunk_index: int
    text: str
    _id: Optional[str] = None
    source_type: str = "pdf"            # pdf | image | docx | text
    embedding_id: str = ""              # id of the vector inside the vector store
    metadata: Dict[str, Any] = field(default_factory=dict)
    char_count: int = 0
    created_at: datetime = field(default_factory=utcnow)

    def to_mongo(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload.pop("_id", None)
        return payload