"""Common MCP utilities for GOFR applications.

Provides shared MCP response formatting, error handling, and server utilities
used across all GOFR MCP servers.

Usage:
    from gofr_common.mcp import (
        json_text,
        success_response,
        error_response,
        format_validation_error,
        MCPResponseBuilder,
    )
"""

from gofr_common.mcp.responses import (
    MCPResponseBuilder,
    error_response,
    format_validation_error,
    json_text,
    success_response,
)

__all__ = [
    # Response helpers
    "json_text",
    "success_response",
    "error_response",
    "format_validation_error",
    "MCPResponseBuilder",
]
