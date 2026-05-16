"""Logger module for gofr-agent.

Re-exports from gofr_common.logger for consistent logging across the project.
"""

from gofr_common.logger import (
    ConsoleLogger,
    DefaultLogger,
    Logger,
    StructuredLogger,
)
from gofr_common.logger import (
    get_logger as _get_logger,
)


def get_logger(name: str = "gofr-agent") -> Logger:
    return _get_logger(name)

__all__ = [
    "Logger",
    "DefaultLogger",
    "ConsoleLogger",
    "StructuredLogger",
    "get_logger",
]
