"""
WSGI entry point.

Run the API with either of:

    python wsgi.py                       # development server, all interfaces
    flask --app wsgi:app run --debug     # Flask CLI
    gunicorn -w 2 'wsgi:app'             # optional production-style server

``app`` is also what the test suite imports.
"""

from __future__ import annotations

import os

from app import create_app
from config.settings import get_settings

settings = get_settings()
app = create_app(settings)


if __name__ == "__main__":  # pragma: no cover - manual entry point
    # Default 5003, not 5000: macOS AirPlay Receiver owns 5000 and answers with
# 403/`Server: AirTunes`, which silently shadows the API. Override with PORT.
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5003"))
    debug = settings.app_env == "development"
    # The reloader is disabled by default so background processing threads are not
    # started twice (which would duplicate work and confuse the progress UI).
    app.run(host=host, port=port, debug=debug, use_reloader=False)