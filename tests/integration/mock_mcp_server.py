"""In-process mock MCP server used by integration tests.

Exposes two tools:
  echo  — returns its ``message`` argument unchanged
  add   — returns the sum of ``a`` and ``b``

Starts a uvicorn server on a free port and tears it down after the test session.
"""

from __future__ import annotations

import asyncio
import socket
import threading

import uvicorn
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Server definition
# ---------------------------------------------------------------------------

mcp = FastMCP("mock-test-server")


@mcp.tool()
def echo(message: str) -> str:
    """Echo the message back."""
    return message


@mcp.tool()
def add(a: float, b: float) -> float:
    """Return a + b."""
    return a + b


def _free_port() -> int:
    """Return a free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Lifecycle helpers
# ---------------------------------------------------------------------------


class _UvicornThread(threading.Thread):
    """Run uvicorn in a daemon thread so tests can control its lifecycle."""

    def __init__(self, app: object, host: str, port: int) -> None:
        super().__init__(daemon=True)
        self.config = uvicorn.Config(app, host=host, port=port, log_level="error")
        self.server = uvicorn.Server(self.config)
        self._ready = threading.Event()
        # Monkey-patch the startup signal so we know when it's ready
        _orig_startup = self.server.startup

        async def _startup_and_signal(sockets=None) -> None:  # type: ignore[return]
            await _orig_startup(sockets=sockets)
            self._ready.set()

        self.server.startup = _startup_and_signal  # type: ignore[method-assign]

    def run(self) -> None:  # pragma: no cover – runs in thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.server.serve())

    def wait_ready(self, timeout: float = 10.0) -> None:
        if not self._ready.wait(timeout):
            raise TimeoutError("Mock MCP server did not start in time")

    def shutdown(self) -> None:
        self.server.should_exit = True


# ---------------------------------------------------------------------------
# Module-level server singleton (started once per pytest session via conftest)
# ---------------------------------------------------------------------------

_thread: _UvicornThread | None = None
_port: int | None = None
_host = "127.0.0.1"


def start_server() -> tuple[str, int]:
    """Start the in-process server and return (host, port)."""
    global _thread, _port
    if _thread is not None:
        return _host, _port  # type: ignore[return-value]
    _port = _free_port()
    app = mcp.streamable_http_app()
    _thread = _UvicornThread(app, _host, _port)
    _thread.start()
    _thread.wait_ready()
    return _host, _port


def stop_server() -> None:
    """Stop the in-process server."""
    global _thread
    if _thread is not None:
        _thread.shutdown()
        _thread.join(timeout=5)
        _thread = None


def server_url() -> str:
    """Return the full MCP URL of the running mock server."""
    if _port is None:
        raise RuntimeError("Mock server not started. Call start_server() first.")
    return f"http://{_host}:{_port}/mcp"
