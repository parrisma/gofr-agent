"""Tests for app.mcp_server.mcp_server.create_mcp_server.

We call the tool handler functions directly (bypassing HTTP) by accessing
``mcp._tool_manager`` which FastMCP populates at decoration time.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from gofr_common.web import reset_auth_header_context, set_auth_header_context
from mcp import McpError

from app.agent.agent import AgentResult, GofrAgent
from app.auth import ALL_ACTIVITIES
from app.config import GofrAgentConfig
from app.exceptions import SessionNotFoundError
from app.mcp_server.mcp_server import create_mcp_server
from app.services.pool import SessionPool
from app.services.registry import ServiceRegistry
from app.sessions.store import SessionStore

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


class _AllowAll:
    """AuthService that grants every activity to every token."""

    def authorised_activities(self, token: str) -> str:
        return ",".join(ALL_ACTIVITIES + ["MCPServer*"])


class _DenyAll:
    """AuthService that denies every token."""

    def authorised_activities(self, token: str) -> str:
        return ""


@contextmanager
def _auth_context(token: str | None = "dev-admin-token") -> Generator[None, None, None]:
    """Set the Authorization ContextVar for the duration of a tool call."""
    raw = f"Bearer {token}" if token else ""
    ctx_token = set_auth_header_context(raw)
    try:
        yield
    finally:
        reset_auth_header_context(ctx_token)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_config() -> GofrAgentConfig:
    return GofrAgentConfig()


def _make_registry(pools: dict | None = None, tools: list | None = None) -> MagicMock:
    reg = MagicMock(spec=ServiceRegistry)
    reg.all_pools = pools or {}
    reg.all_tools = tools or []
    reg.register_service = AsyncMock(return_value=[])
    return reg


def _make_agent() -> MagicMock:
    ag = MagicMock(spec=GofrAgent)
    ag.run = AsyncMock(
        return_value=AgentResult(answer="42", steps=[], model="test", tokens_used=10)
    )
    ag.rebuild = MagicMock()
    return ag


def _make_store() -> SessionStore:
    return SessionStore()


async def _call_tool(mcp, tool_name: str, **kwargs):  # type: ignore[return, no-untyped-def]
    """Invoke a registered FastMCP tool by name, bypassing transport.

    The caller must have set the Authorization ContextVar (via ``_auth_context``)
    before calling this helper.
    """
    tool = mcp._tool_manager._tools[tool_name]
    return await tool.fn(**kwargs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPing:
    async def test_ping_returns_ok(self) -> None:
        mcp = create_mcp_server(
            _make_config(), _make_registry(), _make_agent(), _make_store(), _AllowAll()
        )
        with _auth_context():
            result = await _call_tool(mcp, "ping")
        assert result["status"] == "ok"
        assert "timestamp" in result
        assert "version" in result

    async def test_ping_denied_no_token(self) -> None:
        mcp = create_mcp_server(
            _make_config(), _make_registry(), _make_agent(), _make_store(), _AllowAll()
        )
        with _auth_context(token=None), pytest.raises(McpError):
            await _call_tool(mcp, "ping")

    async def test_ping_denied_insufficient_activity(self) -> None:
        mcp = create_mcp_server(
            _make_config(), _make_registry(), _make_agent(), _make_store(), _DenyAll()
        )
        with _auth_context(), pytest.raises(McpError):
            await _call_tool(mcp, "ping")


class TestListServices:
    async def test_empty_registry(self) -> None:
        mcp = create_mcp_server(
            _make_config(), _make_registry(), _make_agent(), _make_store(), _AllowAll()
        )
        with _auth_context():
            result = await _call_tool(mcp, "list_services")
        assert result == []

    async def test_healthy_service_appears(self) -> None:
        pool = MagicMock(spec=SessionPool)
        pool.is_healthy = True
        reg = _make_registry(pools={"rag": pool}, tools=[])
        mcp = create_mcp_server(_make_config(), reg, _make_agent(), _make_store(), _AllowAll())
        with _auth_context():
            result = await _call_tool(mcp, "list_services")
        assert len(result) == 1
        assert result[0]["name"] == "rag"
        assert result[0]["status"] == "healthy"

    async def test_degraded_service(self) -> None:
        pool = MagicMock(spec=SessionPool)
        pool.is_healthy = False
        reg = _make_registry(pools={"svc": pool})
        mcp = create_mcp_server(_make_config(), reg, _make_agent(), _make_store(), _AllowAll())
        with _auth_context():
            result = await _call_tool(mcp, "list_services")
        assert result[0]["status"] == "degraded"

    async def test_list_denied_no_token(self) -> None:
        mcp = create_mcp_server(
            _make_config(), _make_registry(), _make_agent(), _make_store(), _AllowAll()
        )
        with _auth_context(token=None), pytest.raises(McpError):
            await _call_tool(mcp, "list_services")


class TestAsk:
    async def test_ask_returns_answer_and_session_id(self) -> None:
        mcp = create_mcp_server(
            _make_config(), _make_registry(), _make_agent(), _make_store(), _AllowAll()
        )
        with _auth_context():
            result = await _call_tool(mcp, "ask", question="What is 2+2?")
        assert result["answer"] == "42"
        assert "session_id" in result
        assert result["session_id"] != ""

    async def test_ask_reuses_existing_session(self) -> None:
        store = _make_store()
        mcp = create_mcp_server(
            _make_config(), _make_registry(), _make_agent(), store, _AllowAll()
        )
        with _auth_context():
            r1 = await _call_tool(mcp, "ask", question="Hello")
        with _auth_context():
            r2 = await _call_tool(mcp, "ask", question="World", session_id=r1["session_id"])
        assert r1["session_id"] == r2["session_id"]

    async def test_ask_denied_when_activity_missing(self) -> None:
        mcp = create_mcp_server(
            _make_config(), _make_registry(), _make_agent(), _make_store(), _DenyAll()
        )
        with _auth_context(), pytest.raises(McpError):
            await _call_tool(mcp, "ask", question="hi")

    async def test_ask_passes_token_to_agent(self) -> None:
        agent = _make_agent()
        mcp = create_mcp_server(
            _make_config(), _make_registry(), agent, _make_store(), _AllowAll()
        )
        with _auth_context("dev-admin-token"):
            await _call_tool(mcp, "ask", question="hello")
        _, call_kwargs = agent.run.call_args
        assert call_kwargs.get("token") == "dev-admin-token"


class TestResetSession:
    async def test_reset_clears_session(self) -> None:
        store = _make_store()
        mcp = create_mcp_server(
            _make_config(), _make_registry(), _make_agent(), store, _AllowAll()
        )
        with _auth_context():
            r = await _call_tool(mcp, "ask", question="Hello")
        sid = r["session_id"]

        with _auth_context():
            result = await _call_tool(mcp, "reset_session", session_id=sid)
        assert result["status"] == "ok"
        assert result["session_id"] == sid

    async def test_reset_unknown_session_raises(self) -> None:
        mcp = create_mcp_server(
            _make_config(), _make_registry(), _make_agent(), _make_store(), _AllowAll()
        )
        with _auth_context(), pytest.raises(SessionNotFoundError):
            await _call_tool(mcp, "reset_session", session_id="ghost")

    async def test_reset_denied_no_token(self) -> None:
        mcp = create_mcp_server(
            _make_config(), _make_registry(), _make_agent(), _make_store(), _AllowAll()
        )
        with _auth_context(token=None), pytest.raises(McpError):
            await _call_tool(mcp, "reset_session", session_id="any")


class TestRegisterService:
    async def test_register_calls_registry_and_rebuilds(self) -> None:
        reg = _make_registry()
        agent = _make_agent()
        mcp = create_mcp_server(_make_config(), reg, agent, _make_store(), _AllowAll())

        with _auth_context():
            result = await _call_tool(
                mcp,
                "register_service",
                name="new-svc",
                url="http://new/mcp",
            )

        reg.register_service.assert_awaited_once()
        agent.rebuild.assert_called_once()
        assert result["status"] == "registered"
        assert result["name"] == "new-svc"

    async def test_register_denied_no_token(self) -> None:
        mcp = create_mcp_server(
            _make_config(), _make_registry(), _make_agent(), _make_store(), _AllowAll()
        )
        with _auth_context(token=None), pytest.raises(McpError):
            await _call_tool(mcp, "register_service", name="s", url="http://s/mcp")


class TestRefreshServices:
    async def test_refresh_rebuilds_agent(self) -> None:
        agent = _make_agent()
        mcp = create_mcp_server(
            _make_config(), _make_registry(), agent, _make_store(), _AllowAll()
        )
        with _auth_context():
            result = await _call_tool(mcp, "refresh_services")
        agent.rebuild.assert_called_once()
        assert result["status"] == "refreshed"

    async def test_refresh_denied_no_token(self) -> None:
        mcp = create_mcp_server(
            _make_config(), _make_registry(), _make_agent(), _make_store(), _AllowAll()
        )
        with _auth_context(token=None), pytest.raises(McpError):
            await _call_tool(mcp, "refresh_services")

