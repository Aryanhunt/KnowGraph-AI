"""
Route registration.

Flask blueprints are collected here so ``app.py`` only has to call
:func:`register_blueprints`. Adding a feature area means adding one import — the
rest of the application does not change (brief §19).
"""

from __future__ import annotations

from typing import List, Tuple

from flask import Flask

from routes.analytics_routes import bp as analytics_bp
from routes.auth_routes import bp as auth_bp
from routes.chat_routes import bp as chat_bp
from routes.compare_routes import bp as compare_bp
from routes.document_routes import bp as documents_bp
from routes.graph_routes import bp as graph_bp
from routes.research_routes import bp as research_bp
from routes.search_routes import bp as search_bp
from routes.study_routes import bp as study_bp
from routes.system_routes import bp as system_bp

#: Every API blueprint, in registration order.
BLUEPRINTS: Tuple = (
    system_bp,
    auth_bp,
    documents_bp,
    search_bp,
    chat_bp,
    graph_bp,
    study_bp,
    analytics_bp,
    compare_bp,
    research_bp,
)


def register_blueprints(app: Flask) -> List[str]:
    """Attach all blueprints and return their names (useful for diagnostics)."""
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
    return [blueprint.name for blueprint in BLUEPRINTS]