"""
Background processing queue (brief §4).

Document processing runs on a small thread pool so a large scanned PDF does not
block the API: the upload request returns immediately with status ``queued`` and
the UI polls the document's ``processing_status``/``progress`` fields.

Threads (rather than Celery/Redis) are deliberate for an MCA project: the app must
stay simple to install and run offline, and all the heavy work is I/O-bound
(OCR, HTTP calls to Ollama) so the GIL is not the bottleneck. If the machine has
``PROCESSING_SYNC=true`` the pipeline runs inline instead — which is what the test
suite uses.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, List, Optional

from config.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class JobQueue:
    """A tiny wrapper around :class:`ThreadPoolExecutor`."""

    def __init__(self, workers: int = 2) -> None:
        self.workers = max(1, int(workers))
        self._executor = ThreadPoolExecutor(
            max_workers=self.workers, thread_name_prefix="knowgraph-worker"
        )
        self._futures: List[Future] = []
        self._lock = threading.Lock()
        self._submitted = 0
        self._failed = 0
        self._completed = 0

    def submit(self, fn: Callable, *args, **kwargs) -> Future:
        """Queue ``fn`` and log any exception that escapes it."""
        with self._lock:
            self._submitted += 1
        future = self._executor.submit(self._run, fn, args, kwargs)
        with self._lock:
            self._futures = [item for item in self._futures if not item.done()]
            self._futures.append(future)
        return future

    def _run(self, fn: Callable, args: tuple, kwargs: dict):
        try:
            result = fn(*args, **kwargs)
            with self._lock:
                self._completed += 1
            return result
        except Exception:  # noqa: BLE001 - a failed job must never kill the worker
            with self._lock:
                self._failed += 1
            logger.exception("Background job failed: %s", getattr(fn, "__name__", fn))
            return None

    # ------------------------------------------------------------------
    @property
    def active(self) -> int:
        with self._lock:
            return sum(1 for item in self._futures if not item.done())

    def stats(self) -> dict:
        with self._lock:
            return {
                "workers": self.workers,
                "submitted": self._submitted,
                "completed": self._completed,
                "failed": self._failed,
                "active": sum(1 for item in self._futures if not item.done()),
            }

    def shutdown(self, *, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait)


_queue: Optional[JobQueue] = None
_queue_lock = threading.Lock()


def get_job_queue(settings: Optional[Settings] = None) -> JobQueue:
    """Process-wide queue, created once from ``PROCESSING_WORKERS``."""
    global _queue
    current = settings or get_settings()
    with _queue_lock:
        if _queue is None or _queue.workers != max(1, current.processing_workers):
            if _queue is not None:
                _queue.shutdown(wait=False)
            _queue = JobQueue(current.processing_workers)
            logger.info("Processing queue started with %s worker(s)", _queue.workers)
    return _queue


def reset_job_queue() -> None:
    """Tear the queue down (used by tests and graceful shutdown)."""
    global _queue
    with _queue_lock:
        if _queue is not None:
            _queue.shutdown(wait=False)
        _queue = None


def run_in_background(fn: Callable, *args, **kwargs) -> None:
    """
    Run ``fn`` on the pool, or inline when ``PROCESSING_SYNC=true``.

    The synchronous mode exists so tests (and very small deployments) get a
    deterministic, blocking behaviour without changing any calling code.
    """
    settings = get_settings()
    if settings.processing_sync:
        fn(*args, **kwargs)
        return
    get_job_queue(settings).submit(fn, *args, **kwargs)