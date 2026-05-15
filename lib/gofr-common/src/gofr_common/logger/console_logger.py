"""
Console logger using Python's built-in logging module.

A logger implementation that wraps Python's standard logging module,
providing session tracking and consistent formatting.
"""

import logging as python_logging
import uuid
from typing import Any

from .interface import Logger


class ConsoleLogger(Logger):
    """Logger implementation using Python's built-in logging module.

    Logs to console (stderr by default) with session tracking. Uses Python's
    standard logging infrastructure for compatibility with existing logging
    configurations.

    Example:
        logger = ConsoleLogger(name="gofr-dig", level=logging.DEBUG)
        logger.info("Processing request", request_id="abc123")
    """

    def __init__(
        self,
        name: str = "gofr",
        level: int = python_logging.INFO,
        format_string: str = "%(asctime)s [%(levelname)s] [%(name)s] [session:%(session_id)s] %(message)s",
    ):
        """Initialize the console logger.

        Args:
            name: Logger name (e.g., "gofr-np", "gofr-dig", "gofr-plot")
            level: Logging level (logging.DEBUG, logging.INFO, etc.)
            format_string: Log format string (must include %(session_id)s)
        """
        self._name = name
        self._session_id = str(uuid.uuid4())[:8]
        self._logger = python_logging.getLogger(name)
        self._logger.setLevel(level)

        # Only add handler if none exist (avoid duplicate handlers)
        if not self._logger.handlers:
            handler = python_logging.StreamHandler()
            handler.setLevel(level)
            formatter = python_logging.Formatter(format_string)
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)

    def get_session_id(self) -> str:
        """Get the current session ID."""
        return self._session_id

    def _format_extra(self, **kwargs: Any) -> str:
        """Format additional keyword arguments."""
        if not kwargs:
            return ""
        return " " + " ".join(f"{k}={v}" for k, v in kwargs.items())

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log a debug message."""
        extra_msg = self._format_extra(**kwargs)
        self._logger.debug(message + extra_msg, extra={"session_id": self._session_id})

    def info(self, message: str, **kwargs: Any) -> None:
        """Log an info message."""
        extra_msg = self._format_extra(**kwargs)
        self._logger.info(message + extra_msg, extra={"session_id": self._session_id})

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log a warning message."""
        extra_msg = self._format_extra(**kwargs)
        self._logger.warning(message + extra_msg, extra={"session_id": self._session_id})

    def error(self, message: str, **kwargs: Any) -> None:
        """Log an error message."""
        extra_msg = self._format_extra(**kwargs)
        self._logger.error(message + extra_msg, extra={"session_id": self._session_id})

    def critical(self, message: str, **kwargs: Any) -> None:
        """Log a critical message."""
        extra_msg = self._format_extra(**kwargs)
        self._logger.critical(message + extra_msg, extra={"session_id": self._session_id})
