"""
GOFR Common Logger Module

Provides a flexible logging interface for all GOFR projects with session tracking,
structured output, and optional JSON formatting.

Usage:
    from gofr_common.logger import Logger, get_logger, create_logger

    # Get a pre-configured logger for your project
    logger = get_logger("gofr-dig")
    logger.info("Application started")

    # Or create a custom logger with specific settings
    logger = create_logger(
        name="gofr-plot",
        level=logging.DEBUG,
        json_format=True,
        log_file="/var/log/gofr-plot.log"
    )

    # Or use the classes directly
    from gofr_common.logger import StructuredLogger
    logger = StructuredLogger(name="my-service", json_format=True)

Environment Variables:
    {PREFIX}_LOG_LEVEL: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    {PREFIX}_LOG_FILE: Optional file path for log output
    {PREFIX}_LOG_JSON: Set to "true" for JSON output format

    Where {PREFIX} is derived from the logger name (e.g., GOFR_DIG for "gofr-dig")
"""

import logging
import os
from typing import Optional

from .console_logger import ConsoleLogger
from .default_logger import DefaultLogger
from .interface import Logger
from .structured_logger import JsonFormatter, StructuredLogger, TextFormatter


def _get_env_prefix(name: str) -> str:
    """Convert logger name to environment variable prefix.

    Examples:
        "gofr-dig" -> "GOFR_DIG"
        "gofr-plot" -> "GOFR_PLOT"
        "gofr-np" -> "GOFR_NP"
        "gofr-doc" -> "GOFR_DOC"
    """
    return name.upper().replace("-", "_")


def create_logger(
    name: str = "gofr",
    level: Optional[int] = None,
    log_file: Optional[str] = None,
    json_format: Optional[bool] = None,
) -> Logger:
    """Create a new logger instance with the specified configuration.

    If parameters are not provided, they are read from environment variables
    using the pattern {PREFIX}_LOG_LEVEL, {PREFIX}_LOG_FILE, {PREFIX}_LOG_JSON
    where PREFIX is derived from the name.

    Args:
        name: Logger name (e.g., "gofr-dig", "gofr-plot")
        level: Logging level (defaults to INFO or env var)
        log_file: Optional file path for log output
        json_format: If True, output logs as JSON

    Returns:
        A configured Logger instance

    Example:
        # Explicitly configured
        logger = create_logger("gofr-dig", level=logging.DEBUG)

        # From environment (GOFR_DIG_LOG_LEVEL, etc.)
        logger = create_logger("gofr-dig")
    """
    env_prefix = _get_env_prefix(name)

    # Resolve level from env if not provided
    if level is None:
        level_str = os.environ.get(f"{env_prefix}_LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_str, logging.INFO)

    # Resolve log file from env if not provided
    if log_file is None:
        log_file = os.environ.get(f"{env_prefix}_LOG_FILE")

    # Resolve json format from env if not provided
    if json_format is None:
        json_format = os.environ.get(f"{env_prefix}_LOG_JSON", "false").lower() == "true"

    # Resolve SEQ sink from env if available
    seq_url = os.environ.get(f"{env_prefix}_SEQ_URL") or None
    seq_api_key = os.environ.get(f"{env_prefix}_SEQ_API_KEY") or None

    return StructuredLogger(
        name=name,
        level=level if level is not None else logging.INFO,
        log_file=log_file,
        json_format=json_format,
        seq_url=seq_url,
        seq_api_key=seq_api_key,
    )


def get_logger(name: str = "gofr") -> Logger:
    """Get a logger configured from environment variables.

    This is the recommended way to get a logger in GOFR projects.
    Configuration is read from environment variables:
    - {PREFIX}_LOG_LEVEL: DEBUG, INFO, WARNING, ERROR, CRITICAL
    - {PREFIX}_LOG_FILE: Optional file path
    - {PREFIX}_LOG_JSON: "true" for JSON output

    Args:
        name: Logger name (e.g., "gofr-dig", "gofr-plot", "gofr-np", "gofr-doc")

    Returns:
        A configured Logger instance

    Example:
        # In gofr-dig project
        logger = get_logger("gofr-dig")

        # Configure via environment:
        # export GOFR_DIG_LOG_LEVEL=DEBUG
        # export GOFR_DIG_LOG_JSON=true
    """
    return create_logger(name=name)


__all__ = [
    # Interface
    "Logger",
    # Implementations
    "DefaultLogger",
    "ConsoleLogger",
    "StructuredLogger",
    # Formatters (for custom use)
    "JsonFormatter",
    "TextFormatter",
    # Factory functions
    "create_logger",
    "get_logger",
]
