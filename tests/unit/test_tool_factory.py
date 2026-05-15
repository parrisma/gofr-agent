"""Tests for app.agent.tool_factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.types import TextContent
from pydantic_ai import Tool

from app.agent.tool_factory import make_tool, truncate_result
from app.exceptions import AuthorizationError
from app.services.discovery import MCPToolInfo
from app.services.pool import SessionPool
from tests.helpers.dummy_auth_service import DummyAuthService


def _make_info(
    name: str = "search",
    description: str = "Search things",
    service_name: str = "my-svc",
) -> MCPToolInfo:
    return MCPToolInfo(
        name=name,
        description=description,
        input_schema={},
        service_name=service_name,
    )


def _make_pool_with_session(session: MagicMock) -> MagicMock:
    pool = MagicMock(spec=SessionPool)

    @asynccontextmanager
    async def _open_user_session(token: str) -> AsyncIterator[MagicMock]:
        yield session

    pool.open_user_session = _open_user_session
    return pool


def _ctx(token: str = "dev-admin-token") -> MagicMock:
    ctx = MagicMock()
    ctx.deps = token
    return ctx


class TestTruncateResult:
    def test_short_text_unchanged(self) -> None:
        assert truncate_result("hello", 100) == "hello"

    def test_long_text_truncated(self) -> None:
        text = "x" * 200
        result = truncate_result(text, 100)
        assert result.startswith("x" * 100)
        assert "[... truncated]" in result

    def test_long_text_with_url_preserved(self) -> None:
        url = "https://example.com/doc"
        text = "See " + url + " for details. " + "x" * 200
        result = truncate_result(text, 20)
        assert url in result
        assert "[... truncated. URL:" in result

    def test_exact_length_unchanged(self) -> None:
        text = "a" * 50
        assert truncate_result(text, 50) == text


class TestMakeTool:
    def test_tool_name_format(self) -> None:
        info = _make_info(name="get_doc", service_name="rag-svc")
        pool = _make_pool_with_session(MagicMock())
        tool = make_tool(pool, info, DummyAuthService())
        assert isinstance(tool, Tool)
        assert tool.name == "rag-svc__get_doc"

    def test_tool_description(self) -> None:
        info = _make_info(description="Retrieve a document by ID")
        pool = _make_pool_with_session(MagicMock())
        tool = make_tool(pool, info, DummyAuthService())
        assert tool.description == "Retrieve a document by ID"

    async def test_tool_calls_session_call_tool(self) -> None:
        content = TextContent(type="text", text="result text")
        call_result = MagicMock()
        call_result.content = [content]

        session = MagicMock()
        session.call_tool = AsyncMock(return_value=call_result)
        pool = _make_pool_with_session(session)

        info = _make_info(name="search")
        tool = make_tool(pool, info, DummyAuthService())

        output = await tool.function(_ctx(), query="hello")
        session.call_tool.assert_called_once_with("search", {"query": "hello"})
        assert output == "result text"

    async def test_tool_truncates_long_result(self) -> None:
        long_text = "y" * 10_000
        content = TextContent(type="text", text=long_text)
        call_result = MagicMock()
        call_result.content = [content]

        session = MagicMock()
        session.call_tool = AsyncMock(return_value=call_result)
        pool = _make_pool_with_session(session)

        tool = make_tool(pool, _make_info(), DummyAuthService(), max_chars=100)
        output = await tool.function(_ctx())

        assert "[... truncated]" in output
        assert len(output) < 10_000

    async def test_downstream_activity_denied_raises(self) -> None:
        """read token cannot call downstream tools (no MCPServer* grant)."""
        pool = _make_pool_with_session(MagicMock())
        info = _make_info(name="search", service_name="rag")
        tool = make_tool(pool, info, DummyAuthService())

        with pytest.raises(AuthorizationError):
            await tool.function(_ctx(token="dev-read-token"), query="hello")

    async def test_downstream_activity_allowed_with_admin_token(self) -> None:
        content = TextContent(type="text", text="found it")
        call_result = MagicMock()
        call_result.content = [content]

        session = MagicMock()
        session.call_tool = AsyncMock(return_value=call_result)
        pool = _make_pool_with_session(session)

        info = _make_info(name="search", service_name="rag")
        tool = make_tool(pool, info, DummyAuthService())

        output = await tool.function(_ctx(token="dev-admin-token"), query="hello")
        assert output == "found it"

