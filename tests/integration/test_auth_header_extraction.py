"""Phase B0 spike: prove Authorization header extraction from a live FastMCP server.

This test starts a real FastMCP streamable-HTTP server wrapped with
gofr_common AuthHeaderMiddleware, and verifies that the Authorization header
sent by the client is accessible inside a tool handler via
``get_auth_header_from_context()``.

Keep this test: it serves as a regression guard for the header-extraction
mechanism used throughout Phase B.
"""

from __future__ import annotations

import threading

import pytest
import uvicorn
from gofr_common.web import AuthHeaderMiddleware, get_auth_header_from_context
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP

from tests.integration.mock_mcp_server import _free_port


def _build_spike_server() -> object:
    """Build a minimal FastMCP app that echoes the Authorization header."""
    mcp = FastMCP(name="auth-spike")

    @mcp.tool()
    async def get_auth_header() -> dict[str, str]:  # type: ignore[return]
        """Echo the Authorization header from the current request context."""
        raw = get_auth_header_from_context()
        return {"authorization": raw}

    app = mcp.streamable_http_app()
    # Wrap with the middleware so the header is available inside tool handlers.
    return AuthHeaderMiddleware(app)  # type: ignore[return-value]


class _SpikeServerThread(threading.Thread):
    def __init__(self, host: str, port: int) -> None:
        super().__init__(daemon=True)
        app = _build_spike_server()
        cfg = uvicorn.Config(app, host=host, port=port, log_level="error")
        self.server = uvicorn.Server(cfg)
        self._ready = threading.Event()
        orig = self.server.startup

        async def _startup_and_signal(sockets=None) -> None:  # type: ignore[return]
            await orig(sockets=sockets)
            self._ready.set()

        self.server.startup = _startup_and_signal  # type: ignore[method-assign]

    def run(self) -> None:  # pragma: no cover
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.server.serve())

    def wait_ready(self, timeout: float = 10.0) -> None:
        if not self._ready.wait(timeout):
            raise TimeoutError("Spike server did not start in time")

    def shutdown(self) -> None:
        self.server.should_exit = True


@pytest.fixture()
async def spike_url() -> str:  # type: ignore[return]
    port = _free_port()
    host = "127.0.0.1"
    thread = _SpikeServerThread(host, port)
    thread.start()
    thread.wait_ready()
    yield f"http://{host}:{port}/mcp"  # type: ignore[misc]
    thread.shutdown()


@pytest.mark.asyncio
async def test_authorization_header_reaches_tool_handler(spike_url: str) -> None:
    """The Authorization header sent by the client is readable inside a tool."""
    headers = {"Authorization": "Bearer dev-admin-token"}
    async with (
        streamablehttp_client(spike_url, headers=headers) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool("get_auth_header", arguments={})

    assert len(result.content) == 1
    payload = result.content[0]
    assert hasattr(payload, "text")
    import json
    data = json.loads(payload.text)
    assert data["authorization"] == "Bearer dev-admin-token"


@pytest.mark.asyncio
async def test_missing_authorization_header_returns_empty(spike_url: str) -> None:
    """When no Authorization header is sent, context returns an empty string."""
    async with (
        streamablehttp_client(spike_url) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool("get_auth_header", arguments={})

    import json
    data = json.loads(result.content[0].text)
    assert data["authorization"] == ""
