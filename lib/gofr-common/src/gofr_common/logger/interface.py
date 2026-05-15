"""
Logger interface for GOFR projects.

Abstract base class defining the logging contract that all logger
implementations must follow.
"""

from abc import ABC, abstractmethod
from typing import Any


class Logger(ABC):
    """Abstract base class for logging interface.

    All GOFR projects use this interface to ensure consistent logging
    behavior across the entire ecosystem.

    Example:
        class MyLogger(Logger):
            def info(self, message: str, **kwargs: Any) -> None:
                print(f"INFO: {message}")
            # ... implement other methods
    """

    @abstractmethod
    def debug(self, message: str, **kwargs: Any) -> None:
        """Log a debug message.

        Args:
            message: The message to log
            **kwargs: Additional key-value pairs to include in the log
        """
        pass

    @abstractmethod
    def info(self, message: str, **kwargs: Any) -> None:
        """Log an info message.

        Args:
            message: The message to log
            **kwargs: Additional key-value pairs to include in the log
        """
        pass

    @abstractmethod
    def warning(self, message: str, **kwargs: Any) -> None:
        """Log a warning message.

        Args:
            message: The message to log
            **kwargs: Additional key-value pairs to include in the log
        """
        pass

    @abstractmethod
    def error(self, message: str, **kwargs: Any) -> None:
        """Log an error message.

        Args:
            message: The message to log
            **kwargs: Additional key-value pairs to include in the log
        """
        pass

    @abstractmethod
    def critical(self, message: str, **kwargs: Any) -> None:
        """Log a critical message.

        Args:
            message: The message to log
            **kwargs: Additional key-value pairs to include in the log
        """
        pass

    @abstractmethod
    def get_session_id(self) -> str:
        """Get the current session ID.

        Returns:
            The unique session identifier for this logger instance.
        """
        pass
