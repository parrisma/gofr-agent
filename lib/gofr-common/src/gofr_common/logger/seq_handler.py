"""
SEQ HTTP ingestion handler for Python logging.

Ships structured log events to a Datalust SEQ server via its
HTTP ingestion endpoint (/api/events/raw).

Usage:
    handler = SeqHandler(server_url="http://gofr-seq:5341", api_key="...")
    logger.addHandler(handler)

Environment variables (used by StructuredLogger auto-wiring):
    GOFR_DIG_SEQ_URL      — e.g.  http://gofr-seq:5341
    GOFR_DIG_SEQ_API_KEY  — ingestion-scoped API key
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

# SEQ CLEF (Compact Log Event Format) level mapping
_LEVEL_MAP: dict[int, str] = {
    logging.DEBUG: "Debug",
    logging.INFO: "Information",
    logging.WARNING: "Warning",
    logging.ERROR: "Error",
    logging.CRITICAL: "Fatal",
}

# Keys that are part of the CLEF envelope and should not be duplicated
_CLEF_ENVELOPE_KEYS = {
    "@t", "@l", "@mt", "@m", "@x", "@i", "@r",
}

# Standard LogRecord attributes to exclude from extra properties
_SKIP_KEYS = frozenset({
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "module",
    "msecs", "message", "msg", "name", "pathname", "process",
    "processName", "relativeCreated", "stack_info", "thread",
    "threadName", "taskName",
})


def _record_to_clef(record: logging.LogRecord) -> dict[str, Any]:
    """Convert a logging.LogRecord to a SEQ CLEF event dict."""
    event: dict[str, Any] = {
        "@t": datetime.now(timezone.utc).isoformat(),
        "@l": _LEVEL_MAP.get(record.levelno, "Information"),
        "@mt": record.getMessage(),
    }

    # Exception info
    if record.exc_info and record.exc_info[1] is not None:
        import traceback

        event["@x"] = "".join(traceback.format_exception(*record.exc_info))

    # Logger name as source context
    event["SourceContext"] = record.name

    # Session ID (if attached by StructuredLogger)
    session_id = getattr(record, "session_id", None)
    if session_id:
        event["SessionId"] = str(session_id)

    # Extra structured properties
    for key, value in record.__dict__.items():
        if key in _SKIP_KEYS or key == "session_id":
            continue
        # Prefix with uppercase to follow SEQ property convention
        prop_name = key if key[0].isupper() or key.startswith("@") else key
        if prop_name not in _CLEF_ENVELOPE_KEYS:
            event[prop_name] = _safe_serialize(value)

    return event


def _safe_serialize(value: Any) -> Any:
    """Ensure value is JSON-serializable."""
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_serialize(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _safe_serialize(v) for k, v in value.items()}
    return str(value)


class SeqHandler(logging.Handler):
    """Async-buffered logging handler that ships events to SEQ.

    Events are queued and flushed in a background thread to avoid
    blocking the application on network I/O.

    Args:
        server_url: SEQ ingestion base URL (e.g. ``http://gofr-seq:5341``).
        api_key: Optional SEQ API key with Ingest permission.
        batch_size: Flush after this many queued events (default 25).
        flush_interval: Flush at least every N seconds (default 5).
        max_queue_size: Drop events when the queue exceeds this (default 10 000).
    """

    def __init__(
        self,
        server_url: str,
        api_key: Optional[str] = None,
        batch_size: int = 25,
        flush_interval: float = 5.0,
        max_queue_size: int = 10_000,
    ):
        super().__init__()
        self._server_url = server_url.rstrip("/")
        self._api_key = api_key
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=max_queue_size)
        self._shutdown = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._stats_lock = threading.Lock()
        self._events_enqueued = 0
        self._events_dropped_queue_full = 0
        self._post_failures = 0
        self._last_post_error: Optional[str] = None
        self._last_success_utc: Optional[str] = None
        self._warning_interval_seconds = 60.0
        self._last_drop_warning_monotonic = 0.0
        self._last_post_failure_warning_monotonic = 0.0
        self._start_thread()

    def get_stats(self) -> dict[str, Any]:
        """Return a snapshot of SEQ handler health and delivery counters."""
        with self._stats_lock:
            return {
                "events_enqueued": self._events_enqueued,
                "events_dropped_queue_full": self._events_dropped_queue_full,
                "post_failures": self._post_failures,
                "last_post_error": self._last_post_error,
                "last_success_utc": self._last_success_utc,
                "queue_size": self._queue.qsize(),
            }

    def _warn_rate_limited(
        self,
        *,
        reason: str,
        now_monotonic: float,
        last_warning_monotonic: float,
        details: str,
    ) -> float:
        """Emit an internal warning no more than once per interval."""
        if (now_monotonic - last_warning_monotonic) < self._warning_interval_seconds:
            return last_warning_monotonic

        logging.getLogger("gofr_common.seq_handler").warning(
            "SEQ handler warning: %s (%s)", reason, details
        )
        return now_monotonic

    def _start_thread(self) -> None:
        """Start (or restart) the background flush thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._shutdown.clear()
        self._thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="seq-log-shipper"
        )
        self._thread.start()

    # -- public interface -----------------------------------------------------

    def emit(self, record: logging.LogRecord) -> None:
        """Queue a log record for async delivery to SEQ."""
        try:
            # Auto-restart the flush thread if it was killed (e.g. by
            # logging.config.dictConfig triggering atexit handlers).
            if self._thread is None or not self._thread.is_alive():
                self._start_thread()
            clef = _record_to_clef(record)
            self._queue.put_nowait(clef)
            with self._stats_lock:
                self._events_enqueued += 1
        except queue.Full:
            # Drop with rate-limited warning when backpressure is too high
            now_monotonic = time.monotonic()
            with self._stats_lock:
                self._events_dropped_queue_full += 1
                dropped = self._events_dropped_queue_full
                queue_size = self._queue.qsize()
                self._last_drop_warning_monotonic = self._warn_rate_limited(
                    reason="queue_full",
                    now_monotonic=now_monotonic,
                    last_warning_monotonic=self._last_drop_warning_monotonic,
                    details=f"dropped={dropped} queue_size={queue_size}",
                )
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        """Flush remaining events and shut down the background thread."""
        if self._shutdown.is_set():
            return
        self._shutdown.set()
        if self._thread is not None:
            self._thread.join(timeout=self._flush_interval + 2)
        super().close()

    # -- background flusher ---------------------------------------------------

    def _flush_loop(self) -> None:
        """Drain the queue in batches while the handler is alive."""
        while not self._shutdown.is_set():
            try:
                self._drain_batch()
            except Exception:
                pass  # Never let the flush thread die
            self._shutdown.wait(timeout=self._flush_interval)
        # Final drain after shutdown signal
        try:
            self._drain_batch()
        except Exception:
            pass

    def _drain_batch(self) -> None:
        """Send up to ``batch_size`` events to SEQ in one HTTP POST."""
        batch: list[dict[str, Any]] = []
        while len(batch) < self._batch_size:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break

        if not batch:
            return

        payload = "\n".join(json.dumps(evt, default=str) for evt in batch)
        self._post_clef(payload)

    def _post_clef(self, payload: str) -> None:
        """POST a CLEF payload to SEQ's /api/events/raw endpoint."""
        import urllib.error
        import urllib.request

        url = f"{self._server_url}/api/events/raw?clef"
        headers: dict[str, str] = {"Content-Type": "application/vnd.serilog.clef"}
        if self._api_key:
            headers["X-Seq-ApiKey"] = self._api_key

        data = payload.encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5):
                with self._stats_lock:
                    self._last_success_utc = datetime.now(timezone.utc).isoformat()
        except (urllib.error.URLError, OSError):
            # Network issues — increment counters and warn rate-limited.
            now_monotonic = time.monotonic()
            with self._stats_lock:
                self._post_failures += 1
                self._last_post_error = "network_error"
                failures = self._post_failures
                self._last_post_failure_warning_monotonic = self._warn_rate_limited(
                    reason="post_failure",
                    now_monotonic=now_monotonic,
                    last_warning_monotonic=self._last_post_failure_warning_monotonic,
                    details=f"failures={failures}",
                )
