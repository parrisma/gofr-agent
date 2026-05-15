"""
Structured logger with JSON output and file support.

A production-ready logger that supports JSON formatting for log aggregation
systems and optional file output.
"""

import json
import logging
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .interface import Logger

SENSITIVE_KEY_PATTERNS = (
    "token",
    "secret",
    "password",
    "authorization",
    "api_key",
    "apikey",
    "cookie",
)

SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"^Bearer\s+[A-Za-z0-9._\-+/=]+$", re.IGNORECASE),
    re.compile(r"^[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}$"),
    re.compile(r"^[A-Fa-f0-9]{32,}$"),
    re.compile(r"^[A-Za-z0-9+/=]{40,}$"),
)

TRUNCATION_MARKER = "...[truncated]"
MAX_TEXT_VALUE_LENGTH = 2048
MAX_COLLECTION_LENGTH = 50

REQUIRED_FAILURE_FIELDS = {
    "event": "operation_failed",
    "operation": "unknown",
    "stage": "unknown",
    "dependency": "unknown",
    "cause_type": "unknown",
    "remediation": "review_error_and_retry_or_check_dependencies",
}


def _key_is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(pattern in lowered for pattern in SENSITIVE_KEY_PATTERNS)


def _looks_sensitive_value(value: str) -> bool:
    stripped = value.strip()
    return any(pattern.match(stripped) for pattern in SENSITIVE_VALUE_PATTERNS)


def _truncate_string(value: str) -> str:
    if len(value) <= MAX_TEXT_VALUE_LENGTH:
        return value
    return value[:MAX_TEXT_VALUE_LENGTH] + TRUNCATION_MARKER


def _sanitize_value(key: str, value: Any) -> Any:
    if _key_is_sensitive(key):
        return "[REDACTED]"

    if isinstance(value, str):
        if _looks_sensitive_value(value):
            return "[REDACTED]"
        return _truncate_string(value)

    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for dict_key, dict_value in list(value.items())[:MAX_COLLECTION_LENGTH]:
            sanitized[str(dict_key)] = _sanitize_value(str(dict_key), dict_value)
        if len(value) > MAX_COLLECTION_LENGTH:
            sanitized["_truncated_items"] = len(value) - MAX_COLLECTION_LENGTH
        return sanitized

    if isinstance(value, (list, tuple, set)):
        values = list(value)
        sanitized_list = [_sanitize_value(key, item) for item in values[:MAX_COLLECTION_LENGTH]]
        if len(values) > MAX_COLLECTION_LENGTH:
            sanitized_list.append(f"{TRUNCATION_MARKER}({len(values) - MAX_COLLECTION_LENGTH} items)")
        return sanitized_list

    return value


class JsonFormatter(logging.Formatter):
    """JSON formatter for logging records.

    Formats log records as JSON objects suitable for ingestion by
    log aggregation systems like ELK, Splunk, or CloudWatch.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }

        # Add session_id if present
        session_id = getattr(record, "session_id", None)
        if session_id:
            log_data["session_id"] = str(session_id)

        # Add any other custom attributes (from extra kwargs)
        skip_keys = {
            "args", "asctime", "created", "exc_info", "exc_text", "filename",
            "funcName", "levelname", "levelno", "lineno", "module",
            "msecs", "message", "msg", "name", "pathname", "process",
            "processName", "relativeCreated", "stack_info", "thread",
            "threadName", "session_id", "taskName",
        }

        for key, value in record.__dict__.items():
            if key not in skip_keys:
                log_data[key] = _sanitize_value(key, value)

        return json.dumps(log_data)


class TextFormatter(logging.Formatter):
    """Text formatter that appends extra kwargs to the message.

    Formats log records as human-readable text with any extra
    key-value pairs appended to the message.
    """

    def format(self, record: logging.LogRecord) -> str:
        # Format the base message using the standard formatter
        s = super().format(record)

        # Extract and append extra fields
        skip_keys = {
            "args", "asctime", "created", "exc_info", "exc_text", "filename",
            "funcName", "levelname", "levelno", "lineno", "module",
            "msecs", "message", "msg", "name", "pathname", "process",
            "processName", "relativeCreated", "stack_info", "thread",
            "threadName", "session_id", "taskName",
        }

        extra_args = {}
        for key, value in record.__dict__.items():
            if key not in skip_keys:
                extra_args[key] = _sanitize_value(key, value)

        if extra_args:
            s += " " + " ".join(f"{k}={v}" for k, v in extra_args.items())

        return s


class StructuredLogger(Logger):
    """Logger implementation with structured JSON logging and file output.

    A production-ready logger that supports:
    - JSON formatting for log aggregation systems
    - Human-readable text formatting for development
    - File output with automatic rotation
    - Session tracking across all log entries
    - Optional SEQ ingestion (auto-enabled when seq_url is set)

    Example:
        # Development mode (text output)
        logger = StructuredLogger(name="gofr-plot")

        # Production mode (JSON output to file + SEQ)
        logger = StructuredLogger(
            name="gofr-plot",
            json_format=True,
            log_file="/var/log/gofr-plot.log",
            seq_url="http://gofr-seq:5341",
            seq_api_key="...",
        )

        logger.info("Request processed", request_id="abc123", duration_ms=45)
    """

    def __init__(
        self,
        name: str = "gofr",
        level: int = logging.INFO,
        log_file: Optional[str] = None,
        json_format: bool = False,
        seq_url: Optional[str] = None,
        seq_api_key: Optional[str] = None,
    ):
        """Initialize the structured logger.

        Args:
            name: Logger name (e.g., "gofr-np", "gofr-dig", "gofr-plot", "gofr-doc")
            level: Logging level (logging.DEBUG, logging.INFO, etc.)
            log_file: Optional file path for log output
            json_format: If True, output logs as JSON; otherwise use text format
            seq_url: Optional SEQ ingestion URL (e.g., http://gofr-seq:5341)
            seq_api_key: Optional SEQ API key with Ingest permission
        """
        self._name = name
        self._session_id = str(uuid.uuid4())[:8]
        self._logger = logging.getLogger(name)
        self._logger.setLevel(level)
        self._default_extra: dict[str, Any] = {}

        # Clear existing handlers to avoid duplication if re-initialized
        if self._logger.hasHandlers():
            self._logger.handlers.clear()

        self._logger.propagate = False

        # Create formatter based on format preference
        if json_format:
            formatter: logging.Formatter = JsonFormatter()
        else:
            formatter = TextFormatter(
                "%(asctime)s [%(levelname)s] [%(name)s] [session:%(session_id)s] %(message)s"
            )

        # Console Handler (stdout)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        self._logger.addHandler(console_handler)

        # File Handler (if configured)
        if log_file:
            try:
                file_handler = logging.FileHandler(log_file)
                file_handler.setFormatter(formatter)
                self._logger.addHandler(file_handler)
            except Exception as e:
                # Fallback to console if file cannot be opened
                self._logger.error(
                    "Failed to setup log file",
                    extra={"log_file": log_file, "error": str(e)},
                )

        # SEQ Handler (if configured)
        if seq_url:
            try:
                from .seq_handler import SeqHandler

                seq_handler = SeqHandler(
                    server_url=seq_url,
                    api_key=seq_api_key,
                )
                seq_handler.setLevel(level)
                self._logger.addHandler(seq_handler)
            except Exception as e:
                self._logger.error(
                    "Failed to setup SEQ handler",
                    extra={"seq_url": seq_url, "error": str(e)},
                )

    def get_session_id(self) -> str:
        """Get the current session ID."""
        return self._session_id

    def _log(self, level: int, message: str, **kwargs: Any) -> None:
        """Internal logging method with extra kwargs handling."""
        extra = {"session_id": self._session_id}

        # Merge default extra fields (e.g. build_number) set externally
        if hasattr(self, "_default_extra"):
            extra.update(self._default_extra)

        # Filter out reserved LogRecord attributes to prevent overwrite errors
        reserved_keys = {
            "args", "asctime", "created", "exc_info", "exc_text", "filename",
            "funcName", "levelname", "levelno", "lineno", "module",
            "msecs", "message", "msg", "name", "pathname", "process",
            "processName", "relativeCreated", "stack_info", "thread",
            "threadName", "taskName",
        }

        for k, v in kwargs.items():
            if k not in reserved_keys:
                extra[k] = _sanitize_value(k, v)
            else:
                # Prefix reserved keys to preserve them but avoid collision
                extra[f"_{k}"] = _sanitize_value(k, v)

        if level >= logging.WARNING:
            for req_key, default_value in REQUIRED_FAILURE_FIELDS.items():
                extra.setdefault(req_key, default_value)

        self._logger.log(level, message, extra=extra)

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log a debug message."""
        self._log(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        """Log an info message."""
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log a warning message."""
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        """Log an error message."""
        self._log(logging.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs: Any) -> None:
        """Log a critical message."""
        self._log(logging.CRITICAL, message, **kwargs)
