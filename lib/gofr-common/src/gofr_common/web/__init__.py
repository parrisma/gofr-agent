"""Common web utilities for GOFR projects.

Provides shared web middleware, CORS configuration, and health check utilities
used across all GOFR microservices.
"""

from gofr_common.web.app import (
    create_mcp_starlette_app,
    create_starlette_app,
)
from gofr_common.web.cors import (
    CORSConfig,
    create_cors_middleware,
    get_cors_origins,
)
from gofr_common.web.health import (
    create_health_response,
    create_health_routes,
    create_ping_response,
)
from gofr_common.web.middleware import (
    AuthHeaderMiddleware,
    RequestLoggingMiddleware,
    get_auth_header_from_context,
    reset_auth_header_context,
    set_auth_header_context,
)

__all__ = [
    # CORS
    "CORSConfig",
    "create_cors_middleware",
    "get_cors_origins",
    # Middleware
    "AuthHeaderMiddleware",
    "RequestLoggingMiddleware",
    "get_auth_header_from_context",
    "set_auth_header_context",
    "reset_auth_header_context",
    # Health checks
    "create_health_routes",
    "create_ping_response",
    "create_health_response",
    # App factories
    "create_starlette_app",
    "create_mcp_starlette_app",
]
