"""
Default logger implementation with session tracking.

A simple logger that writes to stderr with timestamps and session IDs.
Suitable for development and simple deployments.
"""

import sys
import uuid
from datetime import datetime, timezone
from typing import Any, TextIO

from .interface import Logger


class DefaultLogger(Logger):
    """Default logger implementation with session tracking.

    A lightweight logger that writes formatted messages to an output stream
    (default: stderr) with optional timestamps and session tracking.

    Example:
        logger = DefaultLogger()
        logger.info("Application started")
        logger.error("Something failed", error_code="E001")
    """

    def __init__(
        self,
        name: str = "gofr",
        output: TextIO = sys.stderr,
        include_timestamp: bool = True,
    ):
        """Initialize the default logger.

        Args:
            name: Logger name (included in output for identification)
            output: Output stream (default: stderr)
            include_timestamp: Whether to include timestamps in log messages
        """
        self._name = name
        self._session_id = str(uuid.uuid4())
        self._output = output
        self._include_timestamp = include_timestamp

    def get_session_id(self) -> str:
        """Get the current session ID."""
        return self._session_id

    def _format_message(self, level: str, message: str, **kwargs: Any) -> str:
        """Format a log message with session ID and optional timestamp."""
        parts = []

        if self._include_timestamp:
            timestamp = datetime.now(timezone.utc).isoformat()
            parts.append(timestamp)

        parts.append(f"[{level}]")
        parts.append(f"[{self._name}]")
        parts.append(f"[session:{self._session_id[:8]}]")
        parts.append(message)

        # Add any additional key-value pairs
        if kwargs:
            extra = " ".join(f"{k}={v}" for k, v in kwargs.items())
            parts.append(f"({extra})")

        return " ".join(parts)

    def _log(self, level: str, message: str, **kwargs: Any) -> None:
        """Internal logging method."""
        formatted = self._format_message(level, message, **kwargs)
        print(formatted, file=self._output, flush=True)

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log a debug message."""
        self._log("DEBUG", message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        """Log an info message."""
        self._log("INFO", message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log a warning message."""
        self._log("WARNING", message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        """Log an error message."""
        self._log("ERROR", message, **kwargs)

    def critical(self, message: str, **kwargs: Any) -> None:
        """Log a critical message."""
        self._log("CRITICAL", message, **kwargs)
