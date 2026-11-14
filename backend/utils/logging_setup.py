"""
Logging configuration.

Backend errors must be logged properly (brief §22), so every module logs through
the standard :mod:`logging` package and the app factory calls
:func:`configure_logging` once at boot. Logs go to stdout and, when enabled, to
``backend/logs/app.log``.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_configured = False


def configure_logging(level: str = "INFO", log_dir: Path | None = None, to_file: bool = True) -> None:
    """Configure root logging. Safe to call more than once."""
    global _configured
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    formatter = logging.Formatter(_LOG_FORMAT)

    # Avoid stacking duplicate handlers across Flask's reloader.
    for handler in list(root.handlers):
        if getattr(handler, "_knowgraph", False):
            root.removeHandler(handler)

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    stream._knowgraph = True  # type: ignore[attr-defined]
    root.addHandler(stream)

    if to_file and log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
            file_handler.setFormatter(formatter)
            file_handler._knowgraph = True  # type: ignore[attr-defined]
            root.addHandler(file_handler)
        except OSError as exc:  # pragma: no cover - disk permission problem
            root.warning("File logging disabled: %s", exc)

    # Third-party loggers are noisy at INFO level.
    for noisy in ("chromadb", "httpx", "urllib3", "onnxruntime", "werkzeug"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)