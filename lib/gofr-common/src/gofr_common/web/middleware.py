"""Common middleware for GOFR web servers.

Provides reusable middleware components for authentication,
request context, and logging.
"""

from contextvars import ContextVar
from typing import Any, Optional

# Context variable for storing Authorization header across async boundaries
_auth_header_context: ContextVar[str] = ContextVar("auth_header", default="")


def get_auth_header_from_context() -> str:
    """Get the Authorization header from the current request context.

    Returns:
        The Authorization header value, or empty string if not set.

    Example:
        async def my_handler():
            auth_header = get_auth_header_from_context()
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
    """
    return _auth_header_context.get()


def set_auth_header_context(value: str) -> Any:
    """Set the Authorization header in the current request context.

    Args:
        value: The Authorization header value

    Returns:
        Token for resetting the context later
    """
    return _auth_header_context.set(value)


def reset_auth_header_context(token: Any) -> None:
    """Reset the Authorization header context to previous value.

    Args:
        token: The token returned from set_auth_header_context
    """
    _auth_header_context.reset(token)


class AuthHeaderMiddleware:
    """Starlette middleware to extract Authorization header into context.

    This middleware extracts the Authorization header from incoming requests
    and stores it in a context variable, making it available to async handlers
    and MCP tool implementations.

    Example:
        from starlette.applications import Starlette
        from gofr_common.web import AuthHeaderMiddleware

        app = Starlette(routes=[...])
        app.add_middleware(AuthHeaderMiddleware)
    """

    def __init__(self, app: Any) -> None:
        """Initialize the middleware.

        Args:
            app: The ASGI application to wrap
        """
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        """Process the request.

        Args:
            scope: ASGI scope dict
            receive: ASGI receive callable
            send: ASGI send callable
        """
        if scope["type"] == "http":
            # Extract Authorization header from request
            headers = dict(scope.get("headers", []))
            auth_header = headers.get(b"authorization", b"").decode("utf-8")

            # Set in context
            token = set_auth_header_context(auth_header)
            try:
                await self.app(scope, receive, send)
            finally:
                # Reset context after request completes
                reset_auth_header_context(token)
        else:
            # Pass through non-HTTP requests (websocket, lifespan, etc.)
            await self.app(scope, receive, send)


class RequestLoggingMiddleware:
    """Middleware to log incoming requests.

    Logs request method, path, and timing information.

    Example:
        from gofr_common.web.middleware import RequestLoggingMiddleware
        from gofr_common.logger import ConsoleLogger

        logger = ConsoleLogger(name="my-service")
        app.add_middleware(RequestLoggingMiddleware, logger=logger)
    """

    def __init__(self, app: Any, logger: Optional[Any] = None) -> None:
        """Initialize the middleware.

        Args:
            app: The ASGI application to wrap
            logger: Logger instance (must have info method)
        """
        self.app = app
        self.logger = logger

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        """Process the request.

        Args:
            scope: ASGI scope dict
            receive: ASGI receive callable
            send: ASGI send callable
        """
        if scope["type"] == "http" and self.logger:
            import time

            method = scope.get("method", "UNKNOWN")
            path = scope.get("path", "/")

            start_time = time.time()

            # Capture response status
            response_status = 0

            async def send_wrapper(message: dict) -> None:
                nonlocal response_status
                if message["type"] == "http.response.start":
                    response_status = message.get("status", 0)
                await send(message)

            try:
                await self.app(scope, receive, send_wrapper)
            finally:
                duration_ms = (time.time() - start_time) * 1000
                self.logger.info(
                    f"{method} {path}",
                    status=response_status,
                    duration_ms=round(duration_ms, 2),
                )
        else:
            await self.app(scope, receive, send)
