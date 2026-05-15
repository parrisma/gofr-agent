"""Health check utilities for GOFR web servers.

Provides common health check endpoint patterns that can be used
with both Starlette and FastAPI applications.
"""

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional


def create_ping_response(
    service: str,
    status: str = "ok",
) -> Dict[str, Any]:
    """Create a standard ping response.

    Args:
        service: Service name (e.g., "gofr-plot", "gofr-np")
        status: Status string (default: "ok")

    Returns:
        Dict with status, timestamp, and service name

    Example:
        >>> create_ping_response("gofr-plot")
        {"status": "ok", "timestamp": "2025-01-01T12:00:00", "service": "gofr-plot"}
    """
    return {
        "status": status,
        "timestamp": datetime.now().isoformat(),
        "service": service,
    }


def create_health_response(
    service: str,
    auth_enabled: bool = False,
    healthy: bool = True,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a standard health check response.

    Args:
        service: Service name
        auth_enabled: Whether authentication is enabled
        healthy: Whether the service is healthy
        extra: Additional fields to include in response

    Returns:
        Dict with status, service name, and auth info

    Example:
        >>> create_health_response("gofr-np", auth_enabled=True)
        {"status": "healthy", "service": "gofr-np", "auth_enabled": True}
    """
    response = {
        "status": "healthy" if healthy else "unhealthy",
        "service": service,
        "auth_enabled": auth_enabled,
    }

    if extra:
        response.update(extra)

    return response


def create_health_routes(
    service: str,
    auth_enabled: bool = False,
    health_check: Optional[Callable[[], bool]] = None,
) -> List[Any]:
    """Create standard health check routes for Starlette.

    Creates /ping and /health endpoints.

    Args:
        service: Service name for responses
        auth_enabled: Whether auth is enabled (for health response)
        health_check: Optional callable that returns True if healthy

    Returns:
        List of Starlette Route objects

    Example:
        from starlette.applications import Starlette
        from gofr_common.web import create_health_routes

        routes = [
            # Your routes here...
        ] + create_health_routes("gofr-plot", auth_enabled=True)

        app = Starlette(routes=routes)
    """
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def ping(request: Any) -> JSONResponse:
        return JSONResponse(create_ping_response(service))

    async def health(request: Any) -> JSONResponse:
        healthy = True
        if health_check is not None:
            try:
                healthy = health_check()
            except Exception:
                healthy = False

        response = create_health_response(
            service=service,
            auth_enabled=auth_enabled,
            healthy=healthy,
        )

        status_code = 200 if healthy else 503
        return JSONResponse(response, status_code=status_code)

    return [
        Route("/ping", endpoint=ping, methods=["GET"]),
        Route("/health", endpoint=health, methods=["GET"]),
    ]
