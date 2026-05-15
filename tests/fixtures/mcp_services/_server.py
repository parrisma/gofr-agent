"""Shared server lifecycle utilities for in-process test MCP services."""

from __future__ import annotations

import asyncio
import socket
import threading

import uvicorn
from gofr_common.web import AuthHeaderMiddleware, get_auth_header_from_context


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _require_bearer() -> str:
    """Extract bearer token from the MCP request context.

    Raises ValueError (propagated as MCP error) if the header is absent or empty.
    """
    auth = get_auth_header_from_context()
    if not auth.lower().startswith("bearer "):
        raise ValueError("Missing or malformed Authorization header")
    token = auth[len("bearer "):].strip()
    if not token:
        raise ValueError("Empty bearer token")
    return token


class _UvicornThread(threading.Thread):
    """Run a uvicorn ASGI app in a daemon thread."""

    def __init__(self, app: object, host: str, port: int) -> None:
        super().__init__(daemon=True)
        self.config = uvicorn.Config(app, host=host, port=port, log_level="error")
        self.server = uvicorn.Server(self.config)
        self._ready = threading.Event()
        _orig = self.server.startup

        async def _startup_and_signal(sockets=None) -> None:  # type: ignore[return]
            await _orig(sockets=sockets)
            self._ready.set()

        self.server.startup = _startup_and_signal  # type: ignore[method-assign]

    def run(self) -> None:  # pragma: no cover
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.server.serve())

    def wait_ready(self, timeout: float = 10.0) -> None:
        if not self._ready.wait(timeout):
            raise TimeoutError("Test MCP service did not start in time")

    def shutdown(self) -> None:
        self.server.should_exit = True


def make_service_server(mcp_app) -> tuple[str, int, _UvicornThread]:
    """Start a FastMCP app and return (host, port, thread)."""
    host = "127.0.0.1"
    port = _free_port()
    app = AuthHeaderMiddleware(mcp_app.streamable_http_app())
    thread = _UvicornThread(app, host, port)
    thread.start()
    thread.wait_ready()
    return host, port, thread
