"""Logger module for gofr-agent.

Re-exports from gofr_common.logger for consistent logging across the project.
"""

from gofr_common.logger import ConsoleLogger, DefaultLogger, Logger

__all__ = [
    "Logger",
    "DefaultLogger",
    "ConsoleLogger",
]
