# KnowGraph AI — Local-First Personal Knowledge Management & Learning System

A complete MCA-level project that turns your own study material (PDFs, scans,
images, Word files, notes) into a searchable, question-answerable and
graph-connected knowledge base — **entirely on your own machine**.

> **No online AI API is used anywhere.** No OpenAI, Gemini, Groq, Claude or any
> other hosted model. All inference runs locally through **Ollama**, all OCR runs
> locally through **Tesseract**, all vectors live in a local database, and all
> metadata lives in your local MongoDB. After the one-time dependency and model
> install, the application works with the network switched off.

---

## Table of contents

1. [What it does](#1-what-it-does)
2. [Architecture](#2-architecture)
3. [Technology stack](#3-technology-stack)
4. [Project structure](#4-project-structure)
5. [Installation](#5-installation)
6. [Configuration (.env)](#6-configuration-env)
7. [Running the application](#7-running-the-application)
8. [How the pipeline works](#8-how-the-pipeline-works)
9. [How OCR works](#9-how-ocr-works)
10. [How RAG and citations work](#10-how-rag-and-citations-work)
11. [How the knowledge graph works](#11-how-the-knowledge-graph-works)
12. [Study features and analytics](#12-study-features-and-analytics)
13. [API reference](#13-api-reference)
14. [Testing](#14-testing)
15. [What works offline](#15-what-works-offline)
16. [Troubleshooting](#16-troubleshooting)
17. [Notes for the viva](#17-notes-for-the-viva)
18. [UI design system](#18-ui-design-system)

---

## 1. What it does

Upload study material → the system extracts the text (running OCR automatically
where needed) → chunks it → embeds it → indexes it for search → extracts topics and
concepts → builds a knowledge graph. You can then:

| Capability | What you get |
| --- | --- |
| **Ask My Knowledge** | RAG answers over *all* your documents, with `[1] [2]` citations down to the page |
| **Chat With Document / Subject / Selected** | The same answering engine, scoped to one document, a subject, or a hand-picked set |
| **General AI** | The local model alone, clearly labelled as *not* using your documents |
| **Search** | Keyword, semantic, or hybrid (Reciprocal Rank Fusion) with real scores |
| **Knowledge graph** | Interactive concept graph with **2D and 3D** views: degree-sized hubs, one line style per relation type, focus/dim, hover tooltips, toggleable legend, layout modes (hierarchical/radial/force), and 3D orbit controls — every node and edge keeps its document/page evidence |
| **Flashcards** | Generated from your own text, editable, with spaced review |
| **Quizzes** | MCQ / true-false / short answer, graded by application logic (never the LLM) |
| **Analytics** | Knowledge-gap detection using plain labels, not invented "AI confidence" |
| **Compare** | Common vs unique topics, methodology and variations, each with sources |
| **Research mode** | Structured paper extraction that says *"Not found in document"* instead of guessing |
| **Learning path** | Prerequisite revision order computed from the graph |

Supported file types: **PDF** (digital, scanned, or mixed), **PNG / JPG / JPEG /
WEBP / TIFF / BMP**, **DOCX**, **TXT**, **Markdown**.

### Success criteria → where it is implemented

| # | Requirement | Implementation |
| --- | --- | --- |
| 1 | Register / login | `services/auth_service.py`, `routes/auth_routes.py` (bcrypt + JWT) |
| 2 | Upload a normal PDF | `services/extraction/pdf_extractor.py` (PyMuPDF text layer) |
| 3 | Upload a scanned PDF | same extractor, per-page OCR fallback |
| 4 | Upload an image of notes | `services/extraction/image_extractor.py` |
| 5 | Automatic text extraction | `services/pipeline.py` |
| 6 | Page/source metadata preserved | `document_pages`, `document_chunks` collections |
| 7 | Semantic search | `services/embeddings/`, `services/vector/`, `services/search_service.py` |
| 8 | Ask questions | `services/rag_service.py` |
| 9 | Answers from the local LLM | `services/llm/ollama_llm.py` |
| 10 | Exact source of each answer | `RagService._build_context` + `SourceCitation.jsx` |
| 11 | Knowledge graph | `services/concept_extractor.py`, `graph_service.py`, `components/knowledge/GraphPanel.jsx` (+ 3D: `GraphScene3D.jsx`, `graph-layout.js`) |
| 12 | Flashcards | `services/flashcard_service.py` |
| 13 | Quizzes | `services/quiz_service.py` |
| 14 | Weak-topic tracking | `services/analytics_service.py` |
| 15 | Document comparison | `services/compare_service.py` |
| 16 | No external AI API | All adapters are local; online providers are *rejected in code* |
| 17 | UI restyleable later | Design tokens in `frontend/src/theme/tokens.css` |
---

## 2. Architecture

The layers are strictly separated (brief §17, §19, §20) so any one of them can be
replaced without touching the others:

```
┌──────────────────────────────────────────────────────────┐
│  UI            React 18 + Vite (frontend/)               │
│                design tokens → components → pages        │
├──────────────────────────────────────────────────────────┤
│  API layer     Flask blueprints (backend/routes/)        │
│                thin: validate, call service, wrap JSON   │
├──────────────────────────────────────────────────────────┤
│  Business      services/ (document, rag, graph, study,   │
│  logic         quiz, analytics, compare, research)       │
├──────────────────────────────────────────────────────────┤
│  AI services   llm/  ocr/  embeddings/  vector/          │
│                every one is an interface + adapters,     │
│                chosen by .env — never hard-coded         │
├──────────────────────────────────────────────────────────┤
│  Database      MongoDB (metadata)   Chroma/NumPy (vectors)│
│                Files on disk (never in MongoDB)          │
└──────────────────────────────────────────────────────────┘
```

**Key design decisions**

* **Pluggable AI adapters.** `LLMService`, `OCRService`, `EmbeddingService` and
  `VectorStore` are abstract contracts with concrete adapters selected by
  environment variables. Online providers (OpenAI, Gemini, …) are *explicitly
  rejected* in `services/llm/factory.py` — the local-only rule is enforced in code.
* **Graceful degradation everywhere** (brief §22). A missing Ollama, a broken PDF,
  a failed OCR page or a dead vector database never produces a bare 500; it
  produces a JSON error with `code`, `message` and a `hint` saying exactly what to
  run. Pages and OCR text are stored *before* the fragile later stages, so a failed
  embedding run still leaves the text keyword-searchable and the document can be
  reprocessed.
* **Honesty by design** (brief §11, §15). Scores shown in the UI are real cosine
  similarities or RRF ranks. Analytics labels derive from recorded answers with
  published thresholds. Summaries state whether the model or extractive scoring
  produced them. Research fields that were not found say so.
* **Background processing.** Large files are processed on a small thread pool so
  the API stays responsive; the UI polls stage/progress fields.
  `PROCESSING_SYNC=true` runs the same code inline (used by tests).

---

## 3. Technology stack

| Layer | Technology | Why |
| --- | --- | --- |
| Backend | Python 3.14, Flask 3 | Simple, explicit, easy to defend in a viva |
| Metadata DB | MongoDB + PyMongo | Document-shaped metadata, text search for hybrid search |
| Vector DB | ChromaDB (default) or pure-NumPy store | Both implement the same `VectorStore` contract |
| OCR | Tesseract via pytesseract (PaddleOCR adapter included) | Fully local, per-page confidence |
| PDF | PyMuPDF | Text extraction *and* rasterisation — no Poppler needed |
| LLM | Ollama (HTTP) | Local inference, model swappable by config |
| Embeddings | Ollama (`nomic-embed-text`) or deterministic hashing fallback | No network, no torch |
| Auth | bcrypt + PyJWT | Hashed passwords, signed tokens |
| Frontend | React 18 + Vite + React Router | Fast dev server, no CDN dependencies |
| Graph 2D | Cytoscape.js (bundled locally) | Canvas-based node/edge rendering with zoom-aware labels |
| Graph 3D | three / @react-three/fiber / @react-three/drei | WebGL-powered 3D graph with orbit controls, spatial layout (d3-force-3d), and lazy loading |
| UI icons | lucide-react (bundled locally) | Consistent SVG icon set, no CDN or font dependency |
| UI motion | Hand-written CSS 3D + rAF notebook animation | No animation library; respects `prefers-reduced-motion` |
| Graph view | Cytoscape.js (bundled) | Interactive zoom/pan/select. It renders to a `<canvas>`, so all graph styling lives in the Cytoscape stylesheet — page CSS cannot reach a node or an edge |
| Tests | pytest | 142 tests: auth, upload, OCR, quality, OCR review, chunking, vectors, RAG, grading, knowledge graph, relationship upload |

---

## 4. Project structure

```
KnowGraph-AI/
├── README.md
├── start-all.sh                one-command launcher (check + start everything)
├── start-backend.sh            start only the Flask backend
├── start-frontend.sh           start only the Vite frontend
├── stop-all.sh                 stop backend + frontend
├── .gitignore
├── scripts/                    maintenance & data-migration utilities
│   ├── cleanup_orphaned_graph.py   removes orphaned graph/study data
│   ├── backfill_quiz_answer_events.py
│   ├── backfill_relation_metadata.py
│   ├── fix_analytics_error.py
│   ├── fix_mcq_a.py
│   ├── fix_mcq_b.py
│   ├── fix_port_5001.py
│   └── fix_research_error.py
├── backend/
│   ├── app.py                  Flask factory (JSON errors, CORS, Mongo init)
│   ├── wsgi.py                 entry point: python wsgi.py
│   ├── requirements.txt
│   ├── .env                    created from .env.example
│   ├── config/settings.py      every tunable, read from .env
│   ├── db/
│   │   ├── mongo.py            client + collection names
│   │   ├── indexes.py          all MongoDB indexes (incl. the text-index fix)
│   │   ├── repositories.py     every Mongo query (user-scoped by design)
│   │   └── study_repositories.py  concept / relation / flashcard / quiz stores
│   ├── models/                 dataclasses: document, page, chunk, graph, study
│   ├── routes/                 one blueprint per feature area (10 blueprints)
│   ├── services/
│   │   ├── pipeline.py                   upload -> ready, stage by stage
│   │   ├── document_service.py             upload/list/edit/delete cascade
│   │   ├── auth_service.py                 bcrypt hashing + JWT login/session
│   │   ├── ocr_review_service.py           correction workflow & reindexing
│   │   ├── chunking.py                     page-aware, overlapping chunker
│   │   ├── concept_extractor.py            deterministic concepts + cue-phrase relations
│   │   ├── search_service.py               hybrid retrieval (Reciprocal Rank Fusion)
│   │   ├── rag_service.py                  grounded answering with citations
│   │   ├── graph_service.py                graph reads + learning path
│   │   ├── flashcard_service.py / quiz_service.py
│   │   ├── analytics_service.py      knowledge gaps
│   │   ├── compare_service.py / research_service.py
│   │   ├── relationship_parser.py    user-uploaded relationship files (JSON/JSONL/CSV/TXT/PDF)
│   │   ├── graph_web_check.py        optional online cross-check for relations
│   │   ├── jobs.py                   background thread pool
│   │   ├── llm/                            base + Ollama adapter + prompts + factory
│   │   ├── ocr/                            base + Tesseract + PaddleOCR + null fallback
│   │   ├── embeddings/                     base + Ollama + hashing fallback + factory
│   │   ├── vector/                         base + Chroma + NumPy + factory
│   │   └── extraction/                     PDF / image / DOCX / text extractors + registry
│   ├── storage/                uploads/, pages/, vectorstore/ (git-ignored)
│   ├── tests/                  142 pytest tests
│   ├── utils/                  auth middleware, errors, file/security helpers, JSON, logging
│   └── logs/                   app.log
└── frontend/
    ├── index.html              no CDN scripts
    ├── package.json            deps: React 18, Cytoscape, lucide-react, Vite + plugins
    ├── vite.config.js          /api proxied to the Flask backend
    ├── public/
    │   └── images/             notebook-cover.png, notebook-paper.png (hero animation)
    └── src/
        ├── App.jsx                root React router component
        ├── main.jsx               React 18 mount point
        ├── theme/tokens.css    every colour/radius/shadow/spacing token
        ├── services/           API modules (no fetch inside components)
        ├── context/            Auth, Theme, Toast providers
        ├── components/         19 reusable components + design-system CSS
        │   ├── Notebook.jsx    scroll-driven 3D notebook animation (dashboard hero)
        │   ├── Notebook.css    its 3D transforms, cover and paper-leaf styles
        │   └── Sidebar.jsx     grouped nav with lucide icons + local-first card
        │   └── knowledge/      2D + 3D knowledge-graph UI (ported from "new graph")
        │       ├── KnowledgeWorkspace.jsx  page controller: API + filters + views
        │       ├── GraphPanel.jsx          Cytoscape 2D / React-Three-Fiber 3D switch
        │       ├── GraphScene3D.jsx        3D scene (WebGL, orbit controls, lazy)
        │       ├── GraphInspector.jsx      concept / relationship detail panel
        │       ├── graph-layout.js         spatial layout (d3-force-3d + cytoscape)
        │       ├── graph-theme.js          relation colours + CSS token reader
        │       ├── graph-ui.jsx            small UI primitives (Button, Badge)
        │       ├── preview-data.js         sample graph + client-side filterGraph()
        │       ├── workspace.css           layout + typography styles
        │       └── GraphPanel.css          graph shell (toolbar, legend, controls)
        ├── hooks/              useApi, usePolling
        ├── layouts/            AppLayout   navbar + sidebar + outlet
        └── pages/              15 pages (Analytics, Auth, Chat, Compare, Dashboard,
                                 DocumentDetail, Documents, Flashcards, Graph,
                                 OcrReview, Quiz, Research, ResearchPanel, Search, Settings)
```

There is also a standalone **design prototype** at `improve-know-graph-ai-ui/`
(Next.js 16 + React 19 + Tailwind 4 + shadcn) kept alongside the app. It is a
visual reference only — it uses static sample data and does **not** connect to
the Flask backend. The design language it introduced (oklch-inspired palette,
grouped sidebar with lucide icons, the notebook scroll animation, elevated
cards) has been ported into `frontend/` above.

---

## 5. Installation

### 5.1 Prerequisites (macOS shown; Linux equivalents in brackets)

```bash
brew install python@3.14 node
tap mongodb/brew && brew install mongodb-community && brew services start mongodb-community
brew install tesseract
brew install ollama
```

### 5.2 Pull the local models (one-time, ~2 GB)

```bash
ollama serve &
ollama pull qwen2.5:3b-instruct
ollama pull nomic-embed-text
```

Any instruct model works: change `LLM_MODEL` in `backend/.env` and restart.
Nothing else changes, because model names only exist in configuration.

### 5.3 Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then edit SECRET_KEY at minimum
python wsgi.py              # http://127.0.0.1:5001
```

### 5.4 Frontend

```bash
cd frontend
npm install
npm run dev                 # http://localhost:5173
```

Open **http://localhost:5173**, register, upload a document. The `Settings`
page shows the live status of every local dependency with the exact fix command
when something is missing.

---

## 6. Configuration (.env)

| Variable | Default | Meaning |
| --- | --- | --- |
| `PORT` | `5001` | backend HTTP port (5000 is reserved by macOS AirPlay Receiver) |
| `APP_ENV` | `development` | `development` enables debug logging; `production` silences it |
| `SECRET_KEY` | change me | JWT signing key - **must** be changed |
| `ACCESS_TOKEN_HOURS` | `12` | JWT expiration window |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | frontend origin(s) allowed to call the API |
| `MONGO_URI` / `MONGO_DB_NAME` | `mongodb://127.0.0.1:27017` / `knowgraph` | metadata DB |
| `STORAGE_DIR` | `storage` | where uploads, page images and the vector DB live on disk |
| `LOG_DIR` | `logs` | log file directory (relative to backend/) |
| `LLM_PROVIDER` | `ollama` | the only supported provider; online ones are rejected |
| `LLM_MODEL` | `qwen2.5:3b-instruct` | chat/summary model - swap freely |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | where Ollama listens |
| `LLM_TIMEOUT_SECONDS` | `180` | max wait for the LLM before failing |
| `LLM_TEMPERATURE` | `0.1` | generation randomness (low = deterministic) |
| `LLM_NUM_CTX` | `8192` | context window size |
| `LLM_MAX_TOKENS` | `1024` | max tokens in a response |
| `EMBEDDING_PROVIDER` | `ollama` | `ollama` or `hashing` (model-free, for tests) |
| `EMBEDDING_MODEL` | `nomic-embed-text` | embedding model |
| `EMBEDDING_TIMEOUT_SECONDS` | `60` | max wait for an embedding request |
| `HASHING_EMBEDDING_DIM` | `512` | vector dimension used by the `hashing` fallback |
| `OCR_ENGINE` | `tesseract` | `tesseract`, `paddleocr`, or `none` |
| `OCR_ENABLED` | `true` | master switch — disable OCR entirely if `false` |
| `TESSERACT_CMD` | (auto) | path to the tesseract binary if not on `$PATH` |
| `OCR_LANG` | `eng` | Tesseract language pack(s) |
| `OCR_MIN_CHARS_PER_PAGE` | `80` | below this a PDF page is treated as scanned |
| `PDF_RENDER_ZOOM` | `2.0` | rasterisation scale for OCR (sharper = slower) |
| `OCR_PREPROCESS` | `true` | master switch for pre-OCR image enhancement |
| `OCR_PREPROCESS_STEPS` | empty (=defaults) | enable steps: grayscale, upscale, denoise, contrast, thresholding, deskew, strip_borders |
| `OCR_UPSCALE_FACTOR` / `OCR_CONTRAST_FACTOR` / `OCR_PREPROCESS_MAX_DIM` | `1.0` / `1.5` / `4000` | upscale/contrast params and processed-image size cap |
| `OCR_QUALITY_GOOD_CONFIDENCE` / `OCR_QUALITY_ACCEPTABLE_CONFIDENCE` | `80.0` / `60.0` | quality label thresholds (below acceptable → poor/needs_review) |
| `OCR_QUALITY_MIN_WORDS` | `5` | fewer recognised words → flagged |
| `VECTOR_DB` | `chroma` | `chroma` or `numpy` (zero-dependency fallback) |
| `CHROMA_COLLECTION` | `knowgraph_chunks` | Chroma collection name |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `1000` / `150` | chunking controls |
| `RAG_TOP_K` | `6` | chunks fed to the answer |
| `RAG_MAX_CONTEXT_CHARS` | `8000` | max characters of context sent to the LLM |
| `RAG_HISTORY_TURNS` | `4` | previous Q&A pairs included in the prompt |
| `HYBRID_SEARCH` | `true` | fuse semantic + keyword results (Reciprocal Rank Fusion) |
| `MAX_UPLOAD_MB` | `50` | upload size limit |
| `PROCESSING_WORKERS` / `PROCESSING_SYNC` | `2` / `false` | background thread pool size; `true` runs synchronously (tests) |
| `GRAPH_MIN_CONCEPT_SCORE` | `0.08` | minimum score for a term to be promoted to a graph node |
| `GRAPH_MAX_CONCEPTS_PER_DOC` | `100` | cap on nodes extracted per document |
| `GRAPH_MAX_RELATIONS_PER_CONCEPT` | `8` | cap on edges per node |
| `GRAPH_ENABLE_LLM_RELATIONS` | `true` | let the local LLM discover extra relationships |
| `GRAPH_MAX_LLM_SECTIONS` | `3` | per-document cap on LLM calls (keeps CPU-only runs fast) |
| `GRAPH_LLM_MIN_CONFIDENCE` | `0.55` | minimum model-reported confidence for a new LLM relation |
| `GRAPH_ENABLE_WEB_CHECK` | `false` | optional online cross-check (disabled by default, never required) |
| `GRAPH_WEB_CHECK_TIMEOUT_SECONDS` | `6` | timeout for the optional web cross-check |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_TO_FILE` | `true` | also write logs to `backend/logs/app.log` |

**Never commit `.env`.** It holds the JWT secret. There are no AI API keys by
design, because nothing calls a paid service.---

## 7. Running the application

Two terminals, or one command:

```bash
# --- Option A: one command starts everything in order ---
cd KnowGraph-AI
./start-all.sh
./start-all.sh --check    # run checks only, start nothing
./start-all.sh stop       # stop backend + frontend

# --- Option B: separate terminals ---
# Terminal 1 — backend (from backend/, venv active)
python wsgi.py
# → http://127.0.0.1:5001   (health: /api/system/health)

# Terminal 2 — frontend (from frontend/)
npm run dev
# → http://localhost:5173
```

Make sure MongoDB and Ollama are running first (`brew services start
mongodb-community`, `ollama serve &`). The **Settings page** in the UI shows the
live status of all five local dependencies — no guessing required.

Production-style serving (optional):

```bash
cd backend  && gunicorn -w 2 -b 127.0.0.1:5001 wsgi:app
cd frontend && npm run build && npm run preview
```

**Port note.** macOS AirPlay Receiver binds port 5000 and answers with `403
Forbidden` — so the backend always defaults to **5001** (`wsgi.py`, `PORT=5001`
in `.env`). If you must use another port, set `PORT=xxxx` and update the Vite
proxy in `frontend/vite.config.js`.

Individual start scripts (useful for debugging one layer at a time):

```bash
./start-backend.sh    # creates .venv/.env if missing, then: python wsgi.py
./start-frontend.sh   # npm install if needed, then: npm run dev
./stop-all.sh         # stops backend + frontend (leaves MongoDB/Ollama up)
```

---

## 8. How the pipeline works

Every upload passes through the same stages, and `processing_status` / `progress`
are updated after each one so the UI can show real progress:

```
Upload → validation → type detection → extraction → OCR if needed
       → cleaning → chunking → embedding → vector index
       → metadata (summary/tags/topics) → knowledge graph → completed
```

1. **Validation** — extension + MIME + size limits; filenames sanitised
   (`utils/security.sanitize_filename`); files stored under
   `storage/uploads/<user_id>/` with a UUID prefix. MongoDB stores only paths.
2. **Extraction** — the registry picks the extractor for the extension. PDFs are
   read page by page with PyMuPDF, and **each page decides for itself** whether it
   needs OCR by comparing usable characters with `OCR_MIN_CHARS_PER_PAGE` — that is
   how mixed PDFs work without user input.
3. **Cleaning** (`utils/text.clean_text`) — repairs hyphenated line breaks,
   ligature/OCR artefacts, collapses whitespace, drops page-number noise.
4. **Storage** — pages are written to `document_pages` with `ocr_used`,
   `ocr_confidence` and the page-image path, *before* the fragile later stages, so
   a failure further down never loses the extracted text.
5. **Chunking** — page-aware, overlapping chunks; a chunk never silently crosses a
   page boundary, which keeps citations truthful.
6. **Embedding + indexing** — chunks are embedded with the configured model and
   upserted with metadata (`user_id`, `document_id`, `page_number`, `title`,
   `source_type`). If embedding fails the document is marked failed with a hint;
   vectors from a different model are never mixed into an existing index.
7. **Metadata** — the local model extracts summary/tags/topics as JSON; without
   Ollama a deterministic extractive summary is used and the document records
   `summary_method: "extractive"`.
8. **Knowledge graph** — concepts and typed relations are extracted
   deterministically, each keeping document + page evidence.

Any stage failure marks the document `failed` with an actionable
`processing_error`; `POST /api/documents/<id>/reprocess` re-runs the pipeline
after the cause is fixed.
---

## 9. How OCR works

* **Engine abstraction.** `OCRService` is the contract; Tesseract ships as the
  default and PaddleOCR is included as a working alternative. **PaddleOCR is an
  optional engine** — it pulls in the PaddlePaddle runtime (~1 GB), so it is not
  a pip dependency of the project. To use it, `pip install paddlepaddle
  paddleocr` and then set `OCR_ENGINE=paddleocr` in `backend/.env`. If the
  configured engine is missing, a `NullOCRService` keeps the app running and
  reports the exact reason (`brew install tesseract`) instead of crashing the
  upload.
* **Automatic detection.** `needs_ocr(text, min_chars)` is a pure function: a page
  with fewer usable characters than the threshold is treated as scanned. Digital
  pages skip OCR entirely — which is why mixed PDFs just work.
* **Rasterisation.** Scanned pages are rendered to PNG by PyMuPDF at
  `PDF_RENDER_ZOOM` and stored under `storage/pages/<document_id>/`, so the page
  image stays available as evidence.
* **Preprocessing.** Before the OCR engine runs, a configurable classical-image
  pipeline can apply grayscale conversion, upscaling, denoising (median filter),
  contrast enhancement, Otsu binarisation, deskewing (projection profiles) and
  border stripping — using Pillow + numpy only. The original page image is never
  modified; a temporary processed copy is passed to OCR and the applied steps are
  recorded in `ocr_preprocessing` metadata. Controlled by `OCR_PREPROCESS` and
  `OCR_PREPROCESS_STEPS` (empty = sensible defaults: grayscale, threshold, deskew).
* **Confidence and quality.** Tesseract's per-word confidences are averaged over
  the words actually recognised and stored per page. On top of that, every OCR
  page gets a *quality report*: `good | acceptable | needs_review | poor |
  unreadable`, with metrics (average/minimum confidence, word/character counts,
  suspicious-character ratio, repeated-character ratio, char-per-word) and
  human-readable warnings. Confidence is *an indicator, not a guarantee* — the
  label is derived from documented, configurable rules (`OCR_QUALITY_*`),
  never from an "AI confidence score".
* **Review and correction.** Low-quality pages stay searchable but are flagged.
  The **OCR review UI** (`/documents/:id/ocr`) shows each page's quality badge,
  metrics, warnings, engine and preprocessing steps, and lets you edit the text,
  save/reset a correction, mark the page reviewed, re-run OCR, and reindex.
  Corrections are stored separately (`corrected_text`); the original OCR output
  (`original_text`) is never overwritten and stays available for audit.
* **Correction-aware search/RAG.** Reindexing rebuilds chunks, embeddings and
  graph links from `effective_text` = `corrected_text` if a valid correction
  exists, otherwise the original text. Chunk/vector ids are deterministic, so
  reindexing replaces instead of duplicating. A failed reindex keeps the
  correction and leaves `needs_reindex: true` so a later retry can finish it.
* **Failure mode.** A page OCR cannot read is preserved with its image and a clear
  message; the rest of the document still processes.

### 9.1 Relationship accuracy (evidence-based graph)

Not every association deserves an edge. The Knowledge Graph uses a **hybrid,
evidence-based** extractor so the graph is built from sentences, headings,
lists, and — where useful — the local LLM, with full provenance on every edge.

**Evidence classes**

| Class | How it is detected | Method | Verification | Default confidence |
| --- | --- | --- | --- | --- |
| **Explicit cue phrase** | A sentence names two concepts **and** contains a cue, e.g. "X **requires** Y", "X **builds on** Y", "X **is a type of** Y", "X **causes** Y", "X **is used for** Y", "X **is an example of** Y", "X **contrasts with** Y". | `cue_phrase` | `verified` | **≥ 0.75** (0.90 when coupled with verbatim evidence) |
| **Rule / structural** | Heading/fan-out/list structure: "Components of X: A, B, …", "Types of X: …", "Applications of X: …", "X uses A, B relations", and the same rule/cue patterns. | `rule` / `structural` | `verified` | **0.85** (structural), **0.90** (rule/cue + evidence) |
| **Local LLM (inferred)** | The local Ollama model proposes new relationships it reads inside a **section** of the page text. It must use terms from the extracted concept list only, and must quote the exact supporting sentence. | `llm` | `inferred` | **0.55–0.65** (boosted toward 0.65 when two or more evidence items back the same edge) |
| **Weak co-occurrence** | Two concepts appear in the same sentence. A single shared sentence is **not** enough — the extractor requires the pair to co-occur in **≥ 2 sentences** in the document before it becomes an edge, and even then it stays weak. | `cooccurrence` | `uncertain` | **0.30** |

**Rules enforced at storage level (`RelationRepository.upsert`)**

* **Source ≠ target** — self-loops are refused.
* **One edge per `user + source_slug + target_slug + relation`** — repeat evidence **strengthens** the edge (weight), it **never duplicates it**.
* **Contradictory types on the same ordered pair are refused**: `prerequisite_of`/`part_of`, `is_a`/`contrasts_with`, `causes`/`contrasts_with`, `example_of`/`contrasts_with` cannot coexist on the same ordered pair; the existing edge keeps its meaning.
* **Every edge stores full provenance**:
  - `confidence` — a deterministic, documented number from the method/evidence table above (never fabricated)
  - `verification_status` — `verified` (text/typed by rule or cue), `inferred` (LLM), `uncertain` (repeated co-occurrence)
  - `evidence_count`
  - `evidence[]` — per-evidence item: `document_id`, `page_number`, `snippet`, `chunk_id`, `method`, and per-evidence `confidence` + `verification_status`
  - `method`
  - `created_at`

**Visible edge styles (graph panel)**

Edges shown in the Cytoscape panel use these visual conventions:

* **Solid** = verified (cue_phrase, rule, structural).
* **Dashed** = inferred (LLM).
* **Faint** = uncertain (repeated co-occurrence, low confidence).

**Relationship types the system can store**

The stored vocabulary now includes `contains`, `component_of`, `type_of`, `application_of`, `defines`, `is_a`, `used_for`, `depends_on`, `prerequisite_of`, `requires`, `example_of`, `contrasts_with`, `part_of`, `explains`, and `related_to`, so edges like the following appear naturally:

* Soft Computing **contains** Neural Networks / Fuzzy Systems / Evolutionary Algorithms / Swarm Intelligence.
* AI **contains** Knowledge Base / Control Strategy / Inference Mechanism.
* Semantic Network **uses_relation** isa / inst.
* "X **is a type of** Y" → `type_of`, "X **is an example of** Y" → `example_of`, "X **depends on** Y" → `depends_on`, "X **causes** Y" → `causes`.

**Filtering and edge inspection**

* `GET /api/graph` returns only **verified** edges by default.
* `?verification=all` (or the graph's **Verified / Inferred / All** selector) reveals **inferred** and **uncertain** edges.
* `?min_confidence=0.9` applies an explicit confidence floor.
* Filtering **hides, it never deletes**.
* Clicking an edge opens the **edge inspector** (`GET /api/graph/relations/evidence?source=…&target=…&relation=…`) which returns: the relation type, confidence, verification status, source/target labels, exact evidence text, document, page, extraction method, and the full evidence trail.
* `POST /api/graph/relations/verify` accepts or rejects an edge; rejected = hidden in the current view, but **still stored** with provenance.

**Reprocessing**

Reprocessing a document removes that document's existing concepts and relations, then re-extracts everything from the file, so the graph never accumulates stale evidence. Evidence provenance (`document_id`, `page_number`, `chunk_id`, `method`, `confidence`, `verification_status`) is preserved by the new extraction and stored as normal.

**Why this matters (the problem we fixed)**

Before this change, the graph depended too heavily on a small cue-phrase list and the LLM only refined relations the deterministic pass had already found, which meant many real documents produced lots of nodes and very few relationships. The hybrid extractor now finds containment/fan-out/type/application relations from headings and lists, adds rule-based confidence bands, lets the LLM **discover new** typed edges, and keeps weak co-occurrence honest (`uncertain`) so the graph is both richer and more explainable.

---

## 10. How RAG and citations work

```
question → query embedding → hybrid retrieval → context assembly
         → local Ollama model → answer with [n] citations → sources
```

1. **Retrieval.** `search_service` runs a vector search (cosine) and a keyword
   search (MongoDB `$text`), then merges the ranked lists with Reciprocal Rank
   Fusion. The score shown in the UI is the real similarity, the real RRF value,
   or the text-search score — never an invented number.
2. **Context assembly.** Top chunks become numbered excerpts `[1] [2] …` with
   document titles and pages, trimmed to `RAG_MAX_CONTEXT_CHARS`.
3. **Answering.** The prompt instructs the model to use *only* the excerpts, cite
   them as `[n]`, and reply with the exact sentence *"I could not find this in
   your uploaded documents."* when the context does not contain the answer. If
   retrieval found nothing, that sentence is returned without calling the model.
4. **Citations.** The service marks which sources the answer actually cited
   (`cited: true`) and sorts them first; the UI renders each as a clickable link
   that opens the document on that page.
5. **Chat modes** are retrieval filters: `knowledge` (all documents), `document`,
   `subject`, `selected`, and `general` (no retrieval — the answer is labelled
   `based_on_documents: false` so the UI presents it differently).

---

## 11. How the knowledge graph works

The graph is built by **classical algorithms**, not by an LLM (brief §9):

* **Concepts** — capitalised phrases ("Functional Dependency"), acronyms ("BCNF",
  "TCP") and frequent multi-word terms, scored with a TF-IDF-style formula. A
  concept records every page it appears on, so the panel can list "Found in".
* **Definitions** — sentences matching "X is/are/means …" are stored as the
  concept's definition, giving nodes real content without inventing any. Every
  mention is examined, and the term is matched whether it opens the sentence
  ("BCNF is a normal form where …") or sits before the verb
  ("Unlike search, Hill Climbing is …"), because notes rarely define a term in the
  first sentence that mentions it.
* **Relations** — two deterministic sources: cue phrases in a sentence
  ("requires", "builds on", "is a type of", "in contrast to") produce typed edges
  (`requires`, `prerequisite_of`, `part_of`, `contrasts_with`, …), and co-occurrence
  inside one sentence produces `related_to`. Each edge keeps its page and snippet,
  and the relation's **weight** carries the confidence (a pair seen together once
  gets a thin 0.75 edge, a pair that keeps reappearing a heavy one up to 3.0) rather
  than a threshold that silently discards evidence.
* **LLM refinement is optional** — if Ollama is running it may add typed
  relations, but only between concepts the deterministic pass already found, and
  always inside the allowed relation vocabulary.
* **Learning path** (brief §12) — a breadth-first walk over `prerequisite_of` /
  `requires` / `part_of` edges produces the revision order; the model may add a
  one-line reason per step, but the order itself never depends on it.

### What stops junk becoming a node

A score alone is not enough to earn a place in the graph. Every gate below exists
because a real uploaded ten-slide PDF produced the wrong node without it — the list
is the before/after of that document:

| Rejected | Why it appeared | Gate |
| --- | --- | --- |
| `job job`, `job job job` | n-grams were built from stopword-filtered tokens, so `Job A Job B` looked like "job job" | Windows slide over **consecutive** words of the text, and a window with a repeated word is not a phrase (`raw_words`) |
| `THE`, `TOP`, `BOTTOM`, `HALF`, `GREEDY`, `SPACE` | all-caps table headers and emphasis matched the acronym pattern | An all-caps token is rejected when it is an ordinary English word, or when the document also writes the same word in normal case ("state-space" vouches for `SPACE`; "greedy logic" for `GREEDY`) |
| `Gemini Notebook` — the top-scoring node | the export stamped it in the footer of every page | Running headers/footers that repeat at the edge of ≥ 60 % of pages are removed before extraction (`strip_running_boilerplate`) |
| `Upgrade` | a section title, "The Upgrade: Random-Restart Hill Climbing" | A low-frequency capitalised phrase whose *every* mention is followed by a colon is a caption, not a concept |
| `hill climbing` **and** `Hill Climbing` | the n-gram pass is lowercase, the phrase pass keeps casing | Case variants merge into one node, best-cased form wins, occurrences are not double-counted |
| `third normal` (next to `third normal form`) | a 2-gram fragment of a longer phrase | A fragment contained in a longer, at-least-as-frequent phrase is pruned |

Nothing here is invented or model-dependent: the same text always yields the same
graph, and every node still points back to its pages.

On the same document this took the graph from **27 nodes, 10 of them junk, and
zero definitions** to **14 concepts, no junk, with the main concept's definition
filled in**.

> Rebuilding is per document: an existing graph only changes when its document is
> processed again — `POST /api/documents/:id/reprocess`, or the **Reprocess**
> button. That run is idempotent (it removes the document's previous concepts and
> relations first), so a node can no longer accumulate occurrences and page
> references from repeated processing.

### The graph panel — visual encoding and interactions

`components/knowledge/KnowledgeWorkspace.jsx` is the exact port of the `new graph`
prototype UI (graph view tabs, heading, page tabs, help panel, filter bar,
collapsible in-page menu, below-graph bar, inspector, footer) embedded inside the
original app shell — the app keeps its own `Sidebar`/`Navbar` and `AppLayout`
scroll, so there is only ever one sidebar on `/graph`. Clicking **Menu** in the
graph header slides the knowledge-graph explorer menu open and shut, wired to the
real backend so the old pipeline keeps working: on mount it calls
`GET /api/graph` + `GET /api/graph/status`; selecting a concept calls
`GET /api/graph/concepts/:slug`; selecting a relationship calls
`GET /api/graph/relations/evidence`; verify/reject posts to
`POST /api/graph/relations/verify`; revision plans come from
`GET /api/graph/learning-path`; and relationship files upload to
`POST /api/graph/upload-relations`. Filters stay client-side on the fetched
payload (verification, confidence, topic, search), while the new prototype's
JSON import/export carries over for demo graphs.

`components/knowledge/GraphPanel.jsx` draws that stored graph with Cytoscape.js
(2D) or `components/knowledge/GraphScene3D.jsx` with React Three Fiber (3D).
Cytoscape renders to a `<canvas>`, so **page CSS cannot reach a node or an edge**:
every graph visual is declared in the Cytoscape stylesheet inside the component
(`buildStyle()`), and `components/knowledge/GraphPanel.css` styles only the HTML
shell around the canvas (wrapper, toolbar, tooltip, legend). The names
`kg-dimmed`, `kg-highlighted`, `kg-focus`, `kg-label-hidden` and `kg-edge-hidden`
are Cytoscape classes on canvas elements — *not* CSS classes. Putting them in
the stylesheet file looks plausible and changes nothing, which is exactly how a
"focus does nothing" bug hides. The 3D scene (`GraphScene3D.jsx`) uses a
`d3-force-3d` spatial layout (`components/knowledge/graph-layout.js`), orbit
controls, depth-based dimming and a graceful WebGL-unavailable fallback, and is lazy-loaded in its
own `GraphScene3D.*.js` chunk so the main bundle stays small.

| Visual | Driven by | Why |
| --- | --- | --- |
| Node size (16–46 px) | Number of connections (degree) | Hubs pop, isolated concepts recede |
| Node colour | Degree band (hub / mid / leaf / isolated), or a hash of `node.subject` if the API ever sends one | Importance at a glance; a new `subject` field needs no code change |
| Node ring | Hub nodes, plus the focused node | Cluster centres and the current selection read instantly |
| Edge line style | Relation type | `requires` / `prerequisite_of` solid + arrow head; `part_of` dashed, no head (containment); `contrasts_with` dotted with a tee at both ends (symmetric); `related_to` faint dashed (weakest signal) |
| Edge width | Relation `weight` | Stronger/repeated evidence stands out |
| Node labels | Zoom level + degree rank | Hubs are labelled when zoomed out, everything else appears as you zoom in — the first paint is not a wall of text. Edge labels follow the same rule |
| Tooltip | Hover | Node: degree, documents, mentions, importance score, definition. Edge: relation, method, weight and the page evidence (`documents[]`, falling back to `evidence` / `snippet` / `page`, otherwise an honest "No page evidence recorded") |

Interactions:

* **Click a node** — focuses its closed neighbourhood (everything else dims to
  12 % opacity) and loads the concept panel beside it.
* **Clear focus** button, or a click on empty canvas — drops the focus. The page
  treats `onSelectNode(null)` as a UI-only change and fetches nothing.
* **Legend** — click a relation type to hide/show every edge of that type;
  **Show all** restores them. Each swatch mirrors the line style used on the
  canvas, so the legend doubles as the key to the graph's semantics.
* **Fit / Zoom in / Zoom out** — the canvas keeps its own viewport.

The workspace adds every button from the new prototype, plus the old
backend-connected actions (the prototype's second sidebar is intentionally
omitted — the page scrolls inside the original shell instead):

* In-page Menu — Graph explorer, Concept library (with live count), Relationships,
  Explorer guide; toggled from the graph header, never a second sidebar.
* Topbar — breadcrumbs, live/Preview badge with backend counts, and the graph's collapsible in-page menu (replaces the prototype's second sidebar).
* Heading row — title + Import JSON / Export buttons (import validates the JSON,
  caps preview size, and filters/stores it locally).
* Page tabs — Graph explorer / Concepts (`graph.nodes.length`) / Relationships
  (`graph.edges.length`).
* Help panel + error banner + Reset filters.
* Graph / Concept library / Relationships library views (library rows reuse the
  exact new-prototype row layout, check marks and empty states).
* Below-graph bar ("How to explore") + backend learning-path builder +
  Refresh, Upload relationships and Reload-backend actions wired to the old API.
* Backend status line (`concept_count`, `relation_count`), concept detail,
  evidence, verify/hide actions and relationship upload preserved 1:1.

Three implementation notes worth defending in the viva:

* Degree is computed in the component from the edge list, so a node's size never
  depends on a possibly stale count returned by the API.
* `onSelectNode` is held in a ref: re-rendering the panel (hovering changes
  tooltip state) must never tear down and rebuild the Cytoscape instance, and the
  Graph page passes a plain inline function.
* Nodes are looked up with `getElementById()`, not a `#slug` selector — concept
  slugs can contain spaces or colons, which make a selector invalid and silently
  return nothing.

---

## 12. Study features and analytics

* **Flashcards** are generated from retrieved excerpts. Without the model, a
  deterministic generator turns definition sentences into "What is X?" cards and
  other informative sentences into fill-in-the-blank cards
  (`generation_method` records which path ran). Reviews (easy/medium/hard) set a
  simple 7/3/1-day due rule and feed analytics.
* **Quizzes** support MCQ, true/false and short answer. Grading is plain
  application logic: exact match for MCQ/true-false, word-set-tolerant matching
  for short answers (`QuizService._grade_short_answer`). The LLM never grades.
* **Knowledge gaps** (brief §11) combine quiz answers, flashcard reviews and
  search history into per-topic labels — `Strong`, `Needs Revision`,
  `Frequently Missed`, `Recently Studied`, `Not Yet Studied` — with published
  thresholds (≥ 80 % accuracy over ≥ 3 answers = Strong, and so on). The UI shows
  the legend, so nothing looks like a mysterious score.
* **Learning paths** and **document comparison** round out the study toolset;
  comparisons always carry their source documents, and the
  methodology/variations section is omitted (with an explanatory note) when the
  model is unavailable.

### Deleting a document is a full cascade

Deleting a document removes *everything* derived from it, so nothing lingers in
the graph or Analytics:

* the file on disk, page renders, chunks, pages and vectors;
* graph **concepts** that were only seen in that document (surviving concepts are
  trimmed back to their remaining page references);
* graph **relations** evidenced only by that document;
* **flashcards** and **quizzes** generated from it, plus their **quiz attempts**;
* **study events** (quiz answers, flashcard reviews) recorded against it.

Topics that were *only* ever studied through deleted material still appear in
Analytics, flagged with the explanation *"Original quiz or flashcard for this
topic was deleted; these answers are still counted."* Recorded answers are
facts: they are never silently dropped, so a topic you answered wrongly keeps
showing up in the knowledge-gap list until you re-take a quiz on it.

The Analytics *knowledge gaps* and *all topics* views therefore always show every
topic that has recorded activity, plus every topic found in your documents
(labelled *Not Yet Studied* until you study it) — neither view can be empty
while documents or study events exist.

### Maintenance script: `scripts/cleanup_orphaned_graph.py`

For data created before the cascade was complete (study events without document
ids, concepts pointing at no document, relations with empty evidence), run:

```bash
cd backend
.venv/bin/python ../scripts/cleanup_orphaned_graph.py --dry-run   # preview
.venv/bin/python ../scripts/cleanup_orphaned_graph.py             # delete orphans
```

Options: `--user-id <id>` restricts the cleanup to one user, `--dry-run` only
reports what would be deleted. It removes orphaned **concepts**, **relations**
and **study events** that point at no existing document — the reason deleted
material could previously still appear as graph nodes and knowledge gaps.

#### Other scripts in `scripts/`

These are one-off fix / data-migration utilities created during development
to resolve specific issues found in the live database. They are kept for
reproducibility and for re-running on a different dataset:

| Script | Purpose |
| --- | --- |
| `backfill_quiz_answer_events.py` | Rebuilds per-`quiz_answer` study events from existing quiz attempts so historical quiz data feeds knowledge-gap analytics (idempotent). |
| `backfill_relation_metadata.py` | Backfills missing `confidence` / `verification_status` fields on relation edges that were written by an older pipeline version (idempotent). |
| `fix_analytics_error.py` | Patches the Analytics page to fail loudly (Alert + Retry) instead of rendering an empty tab when the API is unreachable. |
| `fix_mcq_a.py` / `fix_mcq_b.py` | Two-part fix for letter-only MCQ options (`A`, `B`, `C`, `D`) returned by the model — patches extraction helpers and adds validation + a stricter prompt. |
| `fix_port_5001.py` | Moves the backend from port 5000 → 5001 everywhere (wsgi.py, Vite proxy, health checks, README) to avoid the macOS AirPlay Receiver conflict. |
| `fix_research_error.py` | Patches the Research page to show an Alert + Retry when document loading fails, instead of hanging on "Loading documents…". |

### Acronyms and expansions are one node

Notes typically introduce a term once by name ("Artificial Intelligence") and
then use the abbreviation ("AI") for the rest of the document. The extractor
folds a short acronym into the phrase whose initials it matches, so the graph
shows **one** "Artificial Intelligence" node carrying every "AI" mention — and
relation building treats a bare acronym in a sentence as a mention of the
expanded concept, so definitional sentences like "ML is an application of AI"
correctly connect *Machine Learning* and *Artificial Intelligence*. Without
this, a document's most important concepts ended up as isolated nodes.

### Supplying your own relationships

The automatic pipeline is a good start, but you know your material best. The
graph page has an **Upload relationships** button that accepts **PDF, TXT, JSON,
JSONL or CSV** files listing edges you want in the graph:

```json
[
  {"source": "Machine Learning", "target": "Artificial Intelligence",
   "relation": "is_a", "why": "ML is a subset of AI"}
]
```

```jsonl
{"source": "Artificial Intelligence", "relation": "branch_of", "target": "Computer Science", "page": 1}
{"source": "Machine Learning", "relation": "is_an_example_of", "target": "Artificial Intelligence", "page": 3}
```

```text
Machine Learning -> Artificial Intelligence (is_a) — ML is a subset of AI
```

Concept labels are matched against your existing graph ("AI" resolves to
"Artificial Intelligence"), matched edges are stored as **verified** with 0.90
confidence (`method="user_specified"`), and any labels that don't match a
concept are reported back so you can correct them. Common relation types are
normalised to the graph's vocabulary (`is_a`, `requires`, `part_of`, `causes`,
…); any other relation you write is stored **verbatim** rather than dropped, so
domain-specific labels such as `branch_of` or `has_advantage` are preserved. A
JSONL file (one JSON object per line) is often the easiest way to supply a large
hand-curated edge list, and per-edge `chapter`/`page` values are kept as
evidence on the stored edge.

---

## 13. API reference

All endpoints are prefixed with `/api` and return `{"data": …, "meta": …}` on
success or `{"error": {code, message, hint}}` on failure. Authentication uses
`Authorization: Bearer <token>` except where noted.

| Area | Endpoints |
| --- | --- |
| Auth | `POST /auth/register`, `POST /auth/login`, `GET /auth/me`, `POST /auth/change-password` |
| Documents | `POST /documents` (multipart), `GET /documents`, `GET/PATCH/DELETE /documents/:id`, `POST /documents/:id/reprocess`, `GET /documents/:id/pages[/:n]`, `GET /documents/:id/chunks`, `GET /documents/queue`, `/subjects`, `/tags`, `/stats`, `/recent` |
| OCR review | `GET /documents/:id/ocr/review`, `GET /documents/:id/ocr/review/:n`, `PUT /documents/:id/ocr/review/:n/correction`, `DELETE /documents/:id/ocr/review/:n/correction`, `POST /documents/:id/ocr/review/:n/review`, `POST /documents/:id/ocr/review/:n/rerun`, `POST /documents/:id/ocr/reindex` |
| Search | `POST /search`, `GET /search/pages?q=`, `GET /search/history` |
| Chat | `POST /chat/ask`, `GET /chat/modes`, `GET/DELETE /chat/sessions[/:id]` |
| Graph | `GET /graph`, `/graph/status`, `/graph/concepts[/:slug]`, `/graph/relations`, `/graph/learning-path?target=` |
| Study | `POST /study/flashcards/generate`, `GET/PATCH/DELETE /study/flashcards[/:id]`, `POST /study/flashcards/:id/review`, `POST /study/quizzes/generate`, `GET /study/quizzes[/:id]`, `POST /study/quizzes/:id/submit`, `GET /study/quizzes/:id/attempts` |
| Analytics | `GET /analytics/dashboard`, `/knowledge-gaps`, `/progress`, `/topics` |
| Compare | `POST /compare` |
| Research | `GET /research/:id`, `POST /research/:id/action`, `POST /research/compare`, `GET /research/actions` |
| System | `GET /system/health`, `/system/config`, `/system/supported-types`, `/system/session` |

`/api/system/health` is the single place to see whether MongoDB, Ollama, the
embedding model, OCR and the vector store are all up — it returns availability
*and* the reason plus fix command when something is down.

---

## 14. Testing

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/ -q          # 142 tests
python -m pytest tests/test_documents.py -q   # one file
```

The suite is **hermetic**: it forces `EMBEDDING_PROVIDER=hashing`,
`VECTOR_DB=numpy`, `PROCESSING_SYNC=true` and `MONGO_DB_NAME=knowgraph_pytest`
(see `tests/conftest.py`), so it needs no Ollama, no Chroma and never touches
your real data. Tesseract is used for the OCR tests when installed.

Coverage highlights (brief §25): registration/login/password policy, invalid
tokens, upload validation (unsupported type, empty file, missing file), corrupt
PDF failing gracefully, per-user isolation (Alice vs Bob), list filters, delete
cascade, reprocess-after-failure, scanned-PDF OCR, image OCR, chunk page numbers
and overlap, embedding determinism, vector store round trip and user filtering,
RAG citation contract and the no-hits fallback, quiz grading rules, search score
bands, comparison set operations, the research "not found" contract,
analytics label thresholds, OCR preprocessing enable/disable, original-image
preservation, quality labels (good flags vs. poor flags), graceful OCR failure,
correction storage/separation, correction-preferred reindexing, reindex
idempotency, failed-reindex correction preservation, OCR endpoint auth/isolation
and invalid-id handling.

### Manual check for the graph panel

The frontend deliberately ships without a test framework (no Vitest/Jest
dependency to install offline), so `components/knowledge/GraphPanel.jsx` (2D)
and `components/knowledge/GraphScene3D.jsx` (3D) are verified by hand plus one
headless Cytoscape rehearsal of the 2D panel's class/stylesheet plumbing:

```bash
cd frontend
npm run build                       # must compile the JSX with no warnings

# Headless rehearsal of the panel's focus plumbing (no browser needed):
cat > kg-smoke.mjs <<'EOF'
import cytoscape from 'cytoscape'
const cy = cytoscape({ headless: true })
cy.add([
  { data: { id: 'a' } }, { data: { id: 'b' } }, { data: { id: 'c' } },
  { data: { id: 'e1', source: 'a', target: 'b', relation: 'requires' } },
])
cy.getElementById('a').closedNeighborhood().addClass('kg-highlighted')
cy.elements().difference(cy.getElementById('a').closedNeighborhood()).addClass('kg-dimmed')
console.log('dimmed', cy.$('.kg-dimmed').length, 'highlighted', cy.$('.kg-highlighted').length)
EOF
node kg-smoke.mjs && rm kg-smoke.mjs   # prints: dimmed 1 highlighted 3
```

Then, in the browser (backend + frontend running):

1. Upload a PDF, open **Knowledge Graph** → the canvas paints and hub concept
   labels are readable at the fitted zoom. The new sidebar, heading, tabs,
   filter bar and inspector match the `new graph` prototype exactly.
2. Switch the sidebar/page tabs to **Concepts** and **Relationships** → the
   library rows show counts, labels, confidence and check marks; clicking a row
   selects that concept/edge.
3. Toggle **2D ↔ 3D** → the Three.js scene loads lazily into its own
   `GraphScene3D.*.js` chunk; drag to orbit, scroll to zoom, click a node/edge.
4. Click a node → its neighbourhood stays lit, the rest dims, the concept panel
   fills in (backend definition, related concepts and sources win when present).
5. Select a relationship → evidence loads from `/api/graph/relations/evidence`;
   **Verify** marks it verified and **Hide (reject)** hides it via
   `/api/graph/relations/verify`.
6. **Clear focus** (or click empty canvas) → everything returns to full opacity.
7. Hover a node and an edge → tooltip with degree/documents/score, or relation,
   weight and evidence page.
8. Zoom out → only hub labels survive; zoom in → all labels appear.
9. Click `related_to` in the legend → those edges vanish; **Show all** brings
   them back.
10. Type a learning-path target → **Build revision plan** calls
    `/api/graph/learning-path`; Upload relationships posts to
    `/api/graph/upload-relations`; Import/Export JSON handles the demo graph.
11. Graph node colours follow the design tokens, since they are read with
    `readToken()` at build time.

---

## 15. What works offline

| Capability | Works without internet? |
| --- | --- |
| Register / login / upload | ✅ |
| PDF / DOCX / TXT extraction | ✅ |
| OCR (scanned PDFs and images) | ✅ Tesseract is local |
| Chunking, keyword search | ✅ |
| Embeddings and semantic search | ✅ local model (`hashing` works with no model at all) |
| RAG answers, summaries, flashcards, quizzes | ✅ Ollama is local |
| Knowledge graph, learning path, analytics | ✅ deterministic, no model needed |
| Comparison narrative, research structure pass | ✅ via Ollama; deterministic facts without it |

The frontend bundles React, Cytoscape and the 3D graph stack
(three / @react-three/fiber / @react-three/drei / d3-force-3d) locally — there
are no CDN scripts, so even the UI loads with the network off.
---

## 16. Troubleshooting

The **Settings page** shows each of these live; the same information is available
from `GET /api/system/health`.

| Symptom | Cause and fix |
| --- | --- |
| "Ollama is not running" | `ollama serve &`; check `OLLAMA_BASE_URL`. |
| "model 'qwen2.5:3b-instruct' is not installed" | `ollama pull qwen2.5:3b-instruct` (or change `LLM_MODEL`). |
| "Cannot reach MongoDB" | `brew services start mongodb-community`; verify `MONGO_URI`. |
| "OCR is not available" | `brew install tesseract`, or set `OCR_ENGINE=none` for text-only. |
| "The local vector database is unavailable" | Check `VECTOR_DB` and that `backend/storage/vectorstore` is writable; try `VECTOR_DB=numpy`. |
| Document stuck in `queued` | Workers busy — check `/api/documents/queue`; restart the backend if needed. |
| Document `failed` with an embedding error | Ollama/model issue; fix it, then `POST /api/documents/:id/reprocess`. |
| Document `failed` with "No readable text" | Image-only file with OCR off, or a very poor scan. Fix OCR, then reprocess. |
| Search finds nothing | Only processed documents are searched; check the list and try another mode. |
| Answers say "I could not find this…" | Working as intended — the model refuses to invent; upload material on the topic. |
| Frontend shows "Cannot reach the backend" | Flask server not running, or `VITE_API_TARGET` changed. |
| Pages look empty / all API calls return 403 | macOS AirPlay Receiver owns port 5000. The backend defaults to **5001** for this reason — check `curl http://127.0.0.1:5001/api/health`. |
| Tests fail with Mongo errors | A stray `pytest` run may still hold `knowgraph_pytest`; stop it and re-run. |
| Graph looks like uniform spaghetti | Weak signals dominate: click `related_to` (then `part_of`) in the legend to hide them. Loading fewer concepts also helps — the Graph page requests `limit: 120` with `verification=all` and filters client-side. For an even cleaner layout, `npm install cytoscape-fcose` and switch the layout to `fcose`; the two-line swap is documented in `GraphPanel.jsx`. |
| Focus / dim "does nothing" | Graph visuals must be declared in the Cytoscape stylesheet, not in `GraphPanel.css` — Cytoscape paints to a `<canvas>` and page CSS cannot reach it. `kg-dimmed`, `kg-highlighted`, `kg-label-hidden` and `kg-edge-hidden` are Cytoscape classes on canvas elements. A node can also only dim if it has neighbours to compare against. |
| Hover tooltip says "No page evidence recorded" | That relation was stored from repeated co-occurrence without a page reference — `/api/graph/relations` reports the same record. Working as intended, not a data-loss bug. |
| Node labels are missing at first paint | Only hub concepts are labelled while zoomed out (by design); zoom in, or check that the document actually produced relations. |

Logs are written to `backend/logs/app.log` (`LOG_TO_FILE=false` disables this).

---

## 17. Notes for the viva

* **Why a thread pool instead of Celery?** The app must stay a single
  `pip install` project that runs offline. Processing is I/O-bound (OCR, HTTP to
  Ollama), and `PROCESSING_SYNC=true` gives tests a deterministic path through the
  *same* code the server uses.
* **Why two vector stores?** Chroma is the production default; the NumPy store
  proves the `VectorStore` contract is genuinely pluggable and lets the test
  suite run without a second dependency.
* **Why is the graph not LLM-only?** Deterministic extraction is reproducible,
  free, offline, and every edge carries evidence. The model only *adds* typed
  relations, and its output is validated against the concept list.
* **Why "Not found in document"?** A hallucinated methodology section is worse
  than an honest gap; the research panel marks missing fields explicitly.
* **Why word-set short-answer grading?** Students paraphrase; exact string
  equality would mark correct answers wrong, while pure substring matching is
  still strict enough to reject genuinely different answers — both rules are
  visible in `QuizService` and tested.

---

## 18. UI design system

The interface was redesigned to match the standalone prototype in
`improve-know-graph-ai-ui/` (Next.js 16 + React 19 + Tailwind 4). That
prototype uses sample data only, so its **exact stylesheet and structure were
ported** into the real app — every page keeps working against the Flask
backend, it just looks like the prototype now.

### Where the port lives

| Piece | File | Notes |
| --- | --- | --- |
| Full prototype stylesheet | `frontend/src/theme/prototype.css` | Palette, sidebar, topbar, dashboard, notebook, stats, document list, learning card, footer — verbatim values, imported after `base.css` |
| Design tokens re-pointed | `frontend/src/theme/tokens.css` | The app-wide `--kg-*` palette now matches (terracotta primary, paper surfaces, muted status colours, 5–10px radii), so every other page inherits the same combo |
| Serif headings | `base.css` | `Georgia` via `--kg-font-serif` for page titles |
| Sidebar | `components/Sidebar.jsx` | `.sidebar` / `.brand` / `.workspace-picker` / `.nav-group` / `.nav-item` — same three groups (*Workspace / Learn & Explore / Research*), lucide icons, hover + active pill, local-first card — always open in the desktop layout and no dropdown chevron on the workspace picker. Every entry is a real `NavLink`; the document count comes from `/api/documents/stats` |
| Topbar | `components/Navbar.jsx` | `.topbar` / `.breadcrumb` / `.preview-indicator` / `.profile-avatar` — breadcrumb from the current route, live local-AI health dot, search, profile menu with sign-out. The app runs in the prototype's light paper theme only — the Appearance (Light/Dark) control was removed from Settings, so there is no in-app theme switch |
| Layout shell | `layouts/AppLayout.jsx` | `.workspace-app` / `.workspace-main` |
| Dashboard | `pages/Dashboard.jsx` | `.page-heading-row` → sticky `.hero-panel` with the notebook → `.stats-grid` (4 real counters) → `.workspace-lower` with a searchable `.document-list` of recent uploads + the `.learning-card` → `.dashboard-footer` |
| Notebook animation | `components/Notebook.jsx` | React 18 port of the prototype component: scroll-driven 3D book, click-to-toggle, `prefers-reduced-motion` respected, plain `<img>` instead of `next/image` |
| Images | `frontend/public/images/` | `notebook-cover.png`, `notebook-paper.png` served locally |

### The exact look

* **Palette** — background `#f9faf7`, cards/sidebar `#fffefa`, ink `#313930`,
  soft ink `#697064`, primary **terracotta `#b35b3c`** with accent wash
  `#f4e9de`, borders `#e5e8df`, document chips peach/sage/lavender/sand.
* **Type** — Arial for UI text, Georgia (serif) for display headings, with
  italic accents (`All connected.`, `Connect the dots.`).
* **Sidebar** — 238px fixed rail, `WORKSPACE → LEARN & EXPLORE → RESEARCH`
  groups, count pill on *My documents*, ✧ spark on *Ask my knowledge*.
* **Dashboard** — sticky cream hero panel (`#f2e8db`) split 1fr/1fr with the
  notebook on the right; scrolling past it reveals the stats grid and library.
* **Desktop-only** — mobile/off-canvas breakpoints were removed by request; the
  sidebar is always visible and layouts hold their desktop grid. Only
  `prefers-reduced-motion` rules remain (accessibility, not screen size).

### Honest data, prototype looks

The prototype rendered sample documents and flashcards. The ported dashboard
uses the same layout but binds it to real endpoints:

* stat cards ← `GET /api/analytics/dashboard` (documents, pages, chunks,
  flashcards, quiz attempts + average);
* document list ← the dashboard summary's recent uploads, filterable locally,
  each row opening `DocumentDetail`;
* processing rows ← `GET /api/documents/queue` with live `StatusPill` progress;
* flashcard CTA ← real flashcard count from analytics.

### Verifying

```bash
cd frontend
npm run build          # must finish with no errors
npm run dev            # http://localhost:5173
```

Sign in and the Dashboard should show the terracotta/paper theme, the grouped
sidebar, and the notebook hero that opens as you scroll (or on click). All
other pages (Documents, Search, Chat, Graph, Flashcards, Quiz, Analytics,
Compare, Research, Settings, OCR review) keep their functionality and now
share the same palette and typography.
