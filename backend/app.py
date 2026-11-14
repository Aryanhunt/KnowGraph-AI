"""
KnowGraph AI — Flask application factory.

Wiring order (mirrors brief §19: UI → API → business logic → AI services → DB):

1. logging (so the very first failure is recorded),
2. configuration from ``backend/.env`` via :mod:`config.settings`,
3. JSON/error handlers so every response is JSON,
4. MongoDB connection + indexes (optional: the app still boots and reports the
   problem through ``/api/system/health`` when Mongo is down),
5. blueprints.

The factory pattern keeps the app importable by tests and by ``wsgi.py`` without
side effects.
"""

from __future__ import annotations

import logging
from typing import Optional

from flask import Flask, jsonify

from config.settings import Settings, get_settings
from utils.errors import install_error_handlers
from utils.json_utils import install_json_provider
from utils.logging_setup import configure_logging

logger = logging.getLogger(__name__)


def create_app(settings: Optional[Settings] = None) -> Flask:
    """Build a configured Flask application."""
    current = settings or get_settings()
    current.ensure_directories()
    configure_logging(current.log_level, current.log_dir, current.log_to_file)

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=current.secret_key,
        MAX_CONTENT_LENGTH=current.max_upload_mb * 1024 * 1024,
        JSON_SORT_KEYS=False,
        PROPAGATE_EXCEPTIONS=False,
        SETTINGS=current,
    )

    install_json_provider(app)
    install_error_handlers(app)
    _configure_cors(app, current)
    _init_database(app, current)

    from routes import register_blueprints

    register_blueprints(app)
    _register_root_routes(app, current)

    logger.info(
        "KnowGraph AI ready (env=%s, llm=%s/%s, embeddings=%s/%s, ocr=%s, vector=%s)",
        current.app_env,
        current.llm_provider,
        current.llm_model,
        current.embedding_provider,
        current.embedding_model,
        current.ocr_engine,
        current.vector_db,
    )
    return app


def _configure_cors(app: Flask, settings: Settings) -> None:
    """Allow the Vite dev server (and only the configured origins) to call the API."""
    try:
        from flask_cors import CORS

        CORS(
            app,
            resources={r"/api/*": {"origins": settings.cors_origins}},
            supports_credentials=False,
            allow_headers=["Content-Type", "Authorization"],
            methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        )
    except ImportError:  # pragma: no cover - flask-cors is in requirements
        logger.warning("flask-cors is not installed; cross-origin calls from the dev server will fail")


def _init_database(app: Flask, settings: Settings) -> None:
    """
    Connect to MongoDB and create indexes.

    A failure is logged, not raised: the API still starts so the user can see the
    exact problem in ``/api/system/health`` and in the log file.
    """
    try:
        from db.indexes import ensure_indexes
        from db.mongo import init_mongo

        manager = init_mongo(settings)
        ensure_indexes(manager.database)
    except Exception as exc:  # noqa: BLE001 - the app must still boot
        logger.error("MongoDB initialisation failed: %s", exc)
        app.config["DATABASE_ERROR"] = str(exc)


def _register_root_routes(app: Flask, settings: Settings) -> None:
    """Small, dependency-free endpoints used by health checks and the frontend."""

    @app.get("/")
    def index():
        return jsonify(
            {
                "data": {
                    "name": "KnowGraph AI",
                    "description": "Local-first personal knowledge management & learning system",
                    "api_root": "/api",
                    "docs": "/api/system/config",
                }
            }
        )

    @app.get("/api")
    def api_index():
        """List the available API areas (handy during development and in a viva)."""
        return jsonify(
            {
                "data": {
                    "auth": "/api/auth",
                    "documents": "/api/documents",
                    "search": "/api/search",
                    "chat": "/api/chat",
                    "graph": "/api/graph",
                    "study": "/api/study",
                    "analytics": "/api/analytics",
                    "compare": "/api/compare",
                    "research": "/api/research",
                    "system": "/api/system",
                }
            }
        )

    @app.get("/api/health")
    def simple_health():
        """Minimal liveness probe (no dependency checks)."""
        return jsonify({"data": {"status": "ok", "env": settings.app_env}})