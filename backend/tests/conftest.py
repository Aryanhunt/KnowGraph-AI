"""Force the test environment *before* config.settings is imported.

`config.settings` calls `load_dotenv()` at import time, which copies backend/.env
into ``os.environ``. A ``setdefault`` inside a fixture is therefore too late — the
values would keep their .env state. Setting them here (at conftest import time,
which pytest guarantees runs before any test module imports the app) is what makes
the suite hermetic:

* **PROCESSING_SYNC=true** — the pipeline runs inline, so upload responses are
  already processed and assertions are deterministic (no threads, no polling).
* **EMBEDDING_PROVIDER=hashing** + **VECTOR_DB=numpy** — no Ollama and no Chroma
  are required, and results are reproducible.
* **MONGO_DB_NAME=knowgraph_pytest** — a developer's running server keeps using
  `knowgraph`, so tests never read or wipe live data.
* **STORAGE_DIR** — a throwaway directory for the session.
"""

import os
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# --- forced overrides (assign, not setdefault: .env may already define these)
os.environ["MONGO_DB_NAME"] = "knowgraph_pytest"
os.environ["PROCESSING_SYNC"] = "true"
os.environ["PROCESSING_WORKERS"] = "1"
os.environ["EMBEDDING_PROVIDER"] = "hashing"
os.environ["HASHING_EMBEDDING_DIM"] = "128"
os.environ["VECTOR_DB"] = "numpy"
os.environ["LOG_TO_FILE"] = "false"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest-only"
os.environ["OCR_ENABLED"] = "true"

import pytest  # noqa: E402  (imported after the environment is fixed)


@pytest.fixture(scope="session", autouse=True)
def _storage_dir(tmp_path_factory):
    """Point storage at a throwaway directory for the whole session."""
    storage = tmp_path_factory.mktemp("knowgraph-test-storage")
    os.environ["STORAGE_DIR"] = str(storage)
    yield storage


@pytest.fixture()
def settings(_storage_dir):
    """A fresh Settings snapshot, re-read so the forced env above applies."""
    from config.settings import reload_settings
    from db.mongo import reset_mongo

    reset_mongo()
    return reload_settings()


@pytest.fixture()
def app(settings):
    """Flask application wired to the test settings."""
    from app import create_app

    application = create_app(settings)
    application.config.update(TESTING=True)
    return application


@pytest.fixture()
def client(app):
    """Flask test client for API tests (brief §25: auth, upload, permissions)."""
    return app.test_client()


@pytest.fixture()
def clean_mongo(settings):
    """Drop every collection in the test database before and after a test."""
    from db.mongo import COLLECTIONS, get_collection

    def wipe():
        for name in COLLECTIONS.values():
            get_collection(name).delete_many({})

    wipe()
    yield
    wipe()


@pytest.fixture()
def worker_services(settings):
    """
    Deterministic AI adapters for service-level tests.

    Hashing embeddings + the NumPy vector store need no local model, which keeps
    the suite fast and network-free.
    """
    from services.embeddings.factory import get_embedding_service
    from services.vector.factory import get_vector_store

    return {
        "embeddings": get_embedding_service(settings),
        "vectors": get_vector_store(settings),
    }
