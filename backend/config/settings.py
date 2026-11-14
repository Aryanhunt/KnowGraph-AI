"""
Central configuration layer for KnowGraph AI.

Design rule (project brief §2 and §26): *no* model name, engine name or path is
hard-coded anywhere else in the application. Every module asks this settings
object for what it needs, so the whole local AI stack can be re-pointed
(different LLM, different embedding model, different OCR engine, different
vector database) by editing ``backend/.env`` only.

No online AI provider is supported anywhere in this project: the only
LLM/embedding transport that ships with it is Ollama on localhost.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# ``backend/`` directory — all relative paths in this file hang off it.
BASE_DIR: Path = Path(__file__).resolve().parent.parent

# Load backend/.env when present (silently ignored when it is not).
load_dotenv(BASE_DIR / ".env")


# ---------------------------------------------------------------------------
# Typed readers: a malformed .env fails loudly at boot instead of producing a
# confusing error in the middle of a request.
# ---------------------------------------------------------------------------
def _str(key: str, default: str) -> str:
    value = os.getenv(key)
    return default if value is None or value.strip() == "" else value.strip()


def _int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:  # pragma: no cover - configuration mistake
        raise ValueError(f"Environment variable {key}={raw!r} must be an integer") from exc


def _float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:  # pragma: no cover - configuration mistake
        raise ValueError(f"Environment variable {key}={raw!r} must be a number") from exc


def _bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _list(key: str, default: List[str]) -> List[str]:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _path(key: str, default: str) -> Path:
    """Resolve a possibly relative path against the backend directory."""
    raw = _str(key, default)
    candidate = Path(raw).expanduser()
    return candidate if candidate.is_absolute() else (BASE_DIR / candidate).resolve()


@dataclass
class Settings:
    """Snapshot of the runtime configuration (see backend/.env.example)."""

    # --- application -------------------------------------------------------
    app_env: str = "development"
    secret_key: str = "knowgraph-dev-secret-change-me"
    access_token_hours: int = 12
    cors_origins: List[str] = field(default_factory=lambda: ["http://localhost:5173"])

    # --- database ----------------------------------------------------------
    mongo_uri: str = "mongodb://127.0.0.1:27017"
    mongo_db_name: str = "knowgraph"

    # --- storage -----------------------------------------------------------
    storage_dir: Path = field(default_factory=lambda: BASE_DIR / "storage")
    log_dir: Path = field(default_factory=lambda: BASE_DIR / "logs")
    max_upload_mb: int = 50

    # --- local LLM ---------------------------------------------------------
    llm_provider: str = "ollama"
    llm_model: str = "qwen2.5:3b-instruct"
    ollama_base_url: str = "http://127.0.0.1:11434"
    llm_timeout_seconds: int = 180
    llm_temperature: float = 0.1
    llm_num_ctx: int = 8192
    llm_max_tokens: int = 1024

    # --- embeddings --------------------------------------------------------
    embedding_provider: str = "ollama"
    embedding_model: str = "nomic-embed-text"
    embedding_timeout_seconds: int = 60
    hashing_embedding_dim: int = 512

    # --- OCR ---------------------------------------------------------------
    ocr_engine: str = "tesseract"
    ocr_enabled: bool = True
    tesseract_cmd: str = ""
    ocr_lang: str = "eng"
    ocr_min_chars_per_page: int = 80
    pdf_render_zoom: float = 2.0
    # --- OCR preprocessing ---------------------------------------------------
    ocr_preprocess: bool = True
    ocr_preprocess_steps: str = ""        # empty = use per-step defaults
    ocr_upscale_factor: float = 1.0
    ocr_contrast_factor: float = 1.5
    ocr_preprocess_max_dim: int = 4000
    # --- OCR quality thresholds ----------------------------------------------
    ocr_quality_good_confidence: float = 80.0
    ocr_quality_acceptable_confidence: float = 60.0
    ocr_quality_min_words: int = 5

    # --- vector store ------------------------------------------------------
    vector_db: str = "chroma"
    chroma_collection: str = "knowgraph_chunks"

    # --- chunking / retrieval ---------------------------------------------
    chunk_size: int = 1000
    chunk_overlap: int = 150
    rag_top_k: int = 6
    rag_max_context_chars: int = 8000
    rag_history_turns: int = 4
    hybrid_search: bool = True

    # --- background processing --------------------------------------------
    processing_workers: int = 2
    processing_sync: bool = False

    # --- knowledge graph ---------------------------------------------------
    # max concepts per document: large textbooks need more than a small note —
    # a 136-page AI unit has ~160 candidates above the length-adaptive score
    # floor, and capping at 60 silently dropped "Machine Learning" (rank ~86).
    graph_min_concept_score: float = 0.08
    graph_max_concepts_per_doc: int = 100
    graph_max_relations_per_concept: int = 8
    graph_enable_llm_relations: bool = True
    graph_max_llm_sections: int = 3
    graph_llm_min_confidence: float = 0.55
    graph_enable_web_check: bool = False
    graph_web_check_timeout_seconds: int = 6

    # --- logging -----------------------------------------------------------
    log_level: str = "INFO"
    log_to_file: bool = True

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------
    @classmethod
    def from_env(cls) -> "Settings":
        """Build a Settings instance from backend/.env + process environment."""
        return cls(
            app_env=_str("APP_ENV", "development"),
            secret_key=_str("SECRET_KEY", "knowgraph-dev-secret-change-me"),
            access_token_hours=_int("ACCESS_TOKEN_HOURS", 12),
            cors_origins=_list("CORS_ORIGINS", ["http://localhost:5173", "http://127.0.0.1:5173"]),
            mongo_uri=_str("MONGO_URI", "mongodb://127.0.0.1:27017"),
            mongo_db_name=_str("MONGO_DB_NAME", "knowgraph"),
            storage_dir=_path("STORAGE_DIR", "storage"),
            log_dir=_path("LOG_DIR", "logs"),
            max_upload_mb=_int("MAX_UPLOAD_MB", 50),
            llm_provider=_str("LLM_PROVIDER", "ollama").lower(),
            llm_model=_str("LLM_MODEL", "qwen2.5:3b-instruct"),
            ollama_base_url=_str("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/"),
            llm_timeout_seconds=_int("LLM_TIMEOUT_SECONDS", 180),
            llm_temperature=_float("LLM_TEMPERATURE", 0.1),
            llm_num_ctx=_int("LLM_NUM_CTX", 8192),
            llm_max_tokens=_int("LLM_MAX_TOKENS", 1024),
            embedding_provider=_str("EMBEDDING_PROVIDER", "ollama").lower(),
            embedding_model=_str("EMBEDDING_MODEL", "nomic-embed-text"),
            embedding_timeout_seconds=_int("EMBEDDING_TIMEOUT_SECONDS", 60),
            hashing_embedding_dim=_int("HASHING_EMBEDDING_DIM", 512),
            ocr_engine=_str("OCR_ENGINE", "tesseract").lower(),
            ocr_enabled=_bool("OCR_ENABLED", True),
            tesseract_cmd=_str("TESSERACT_CMD", ""),
            ocr_lang=_str("OCR_LANG", "eng"),
            ocr_min_chars_per_page=_int("OCR_MIN_CHARS_PER_PAGE", 80),
            pdf_render_zoom=_float("PDF_RENDER_ZOOM", 2.0),
            ocr_preprocess=_bool("OCR_PREPROCESS", True),
            ocr_preprocess_steps=_str("OCR_PREPROCESS_STEPS", ""),
            ocr_upscale_factor=_float("OCR_UPSCALE_FACTOR", 1.0),
            ocr_contrast_factor=_float("OCR_CONTRAST_FACTOR", 1.5),
            ocr_preprocess_max_dim=_int("OCR_PREPROCESS_MAX_DIM", 4000),
            ocr_quality_good_confidence=_float("OCR_QUALITY_GOOD_CONFIDENCE", 80.0),
            ocr_quality_acceptable_confidence=_float("OCR_QUALITY_ACCEPTABLE_CONFIDENCE", 60.0),
            ocr_quality_min_words=_int("OCR_QUALITY_MIN_WORDS", 5),
            vector_db=_str("VECTOR_DB", "chroma").lower(),
            chroma_collection=_str("CHROMA_COLLECTION", "knowgraph_chunks"),
            chunk_size=_int("CHUNK_SIZE", 1000),
            chunk_overlap=_int("CHUNK_OVERLAP", 150),
            rag_top_k=_int("RAG_TOP_K", 6),
            rag_max_context_chars=_int("RAG_MAX_CONTEXT_CHARS", 8000),
            rag_history_turns=_int("RAG_HISTORY_TURNS", 4),
            hybrid_search=_bool("HYBRID_SEARCH", True),
            processing_workers=_int("PROCESSING_WORKERS", 2),
            processing_sync=_bool("PROCESSING_SYNC", False),
            graph_min_concept_score=_float("GRAPH_MIN_CONCEPT_SCORE", 0.08),
            graph_max_concepts_per_doc=_int("GRAPH_MAX_CONCEPTS_PER_DOC", 100),
            graph_max_relations_per_concept=_int("GRAPH_MAX_RELATIONS_PER_CONCEPT", 8),
            graph_enable_llm_relations=_bool("GRAPH_ENABLE_LLM_RELATIONS", True),
            graph_max_llm_sections=_int("GRAPH_MAX_LLM_SECTIONS", 3),
            graph_llm_min_confidence=_float("GRAPH_LLM_MIN_CONFIDENCE", 0.55),
            graph_enable_web_check=_bool("GRAPH_ENABLE_WEB_CHECK", False),
            graph_web_check_timeout_seconds=_int("GRAPH_WEB_CHECK_TIMEOUT_SECONDS", 6),
            log_level=_str("LOG_LEVEL", "INFO").upper(),
            log_to_file=_bool("LOG_TO_FILE", True),
        )

    # ------------------------------------------------------------------
    # Derived paths
    # ------------------------------------------------------------------
    @property
    def upload_dir(self) -> Path:
        """Original uploaded files live here (never inside MongoDB)."""
        return self.storage_dir / "uploads"

    @property
    def page_image_dir(self) -> Path:
        """Rasterised page images produced during scanned-PDF OCR."""
        return self.storage_dir / "pages"

    @property
    def vector_dir(self) -> Path:
        """Persistent vector database directory."""
        return self.storage_dir / "vectorstore"

    def ensure_directories(self) -> None:
        for directory in (
            self.storage_dir,
            self.upload_dir,
            self.page_image_dir,
            self.vector_dir,
            self.log_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


# Module level singleton. Tests build their own Settings when needed.
settings: Settings = Settings.from_env()


def get_settings() -> Settings:
    return settings


def reload_settings() -> Settings:
    """Re-read the environment (used by the system settings endpoint)."""
    global settings
    settings = Settings.from_env()
    return settings
