"""Shared pytest fixtures for integration tests."""

from __future__ import annotations

import importlib

import pytest

from tests.integration.mock_mcp_server import server_url, start_server, stop_server

# ---------------------------------------------------------------------------
# Existing mock MCP server fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def mock_mcp_server() -> None:
    """Start the in-process mock MCP server for the entire test session."""
    start_server()
    yield  # type: ignore[misc]
    stop_server()


@pytest.fixture(scope="session")
def mock_mcp_url() -> str:
    """Return the URL of the running mock MCP server."""
    return server_url()


# ---------------------------------------------------------------------------
# Auth constants used by test MCP service tests
# ---------------------------------------------------------------------------

TEST_JWT = "test-token-gofr-fixtures"
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_JWT}"}

# ---------------------------------------------------------------------------
# Test MCP service URL fixtures (started on demand, not autouse)
# ---------------------------------------------------------------------------

_instruments_thread = None
_instruments_url: str | None = None


@pytest.fixture(scope="session")
def instruments_url() -> str:  # type: ignore[return]
    global _instruments_thread, _instruments_url
    if _instruments_url is None:
        from tests.fixtures.mcp_services import instruments as instruments_module
        from tests.fixtures.mcp_services._server import make_service_server

        instruments_module = importlib.reload(instruments_module)
        instruments_mcp = instruments_module.mcp

        host, port, thread = make_service_server(instruments_mcp)
        _instruments_thread = thread
        _instruments_url = f"http://{host}:{port}/mcp"
    yield _instruments_url
    if _instruments_thread is not None:
        _instruments_thread.shutdown()
        _instruments_thread.join(timeout=5)


_clients_thread = None
_clients_url: str | None = None


@pytest.fixture(scope="session")
def clients_url() -> str:  # type: ignore[return]
    global _clients_thread, _clients_url
    if _clients_url is None:
        from tests.fixtures.mcp_services._server import make_service_server
        from tests.fixtures.mcp_services.clients import mcp as clients_mcp
        host, port, thread = make_service_server(clients_mcp)
        _clients_thread = thread
        _clients_url = f"http://{host}:{port}/mcp"
    yield _clients_url
    if _clients_thread is not None:
        _clients_thread.shutdown()
        _clients_thread.join(timeout=5)


_trades_thread = None
_trades_url: str | None = None


@pytest.fixture(scope="session")
def trades_url() -> str:  # type: ignore[return]
    global _trades_thread, _trades_url
    if _trades_url is None:
        from tests.fixtures.mcp_services._server import make_service_server
        from tests.fixtures.mcp_services.trades import mcp as trades_mcp
        host, port, thread = make_service_server(trades_mcp)
        _trades_thread = thread
        _trades_url = f"http://{host}:{port}/mcp"
    yield _trades_url
    if _trades_thread is not None:
        _trades_thread.shutdown()
        _trades_thread.join(timeout=5)


_analytics_thread = None
_analytics_url: str | None = None


@pytest.fixture(scope="session")
def analytics_url() -> str:  # type: ignore[return]
    global _analytics_thread, _analytics_url
    if _analytics_url is None:
        from tests.fixtures.mcp_services import analytics as analytics_module
        from tests.fixtures.mcp_services._server import make_service_server

        analytics_module = importlib.reload(analytics_module)
        analytics_mcp = analytics_module.mcp

        host, port, thread = make_service_server(analytics_mcp)
        _analytics_thread = thread
        _analytics_url = f"http://{host}:{port}/mcp"
    yield _analytics_url
    if _analytics_thread is not None:
        _analytics_thread.shutdown()
        _analytics_thread.join(timeout=5)
