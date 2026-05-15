"""Tests for app.services.discovery."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exceptions import ToolDiscoveryError
from app.services import ServiceConfig
from app.services.discovery import discover_tools
from app.services.pool import SessionPool


def _make_service(name: str = "svc") -> ServiceConfig:
    return ServiceConfig(name=name, url="http://svc/mcp")


def _make_pool_with_session(session: MagicMock) -> SessionPool:
    pool = MagicMock(spec=SessionPool)

    @asynccontextmanager
    async def _checkout() -> AsyncIterator[MagicMock]:
        yield session

    pool.checkout = _checkout
    return pool


def _make_tool_mock(name: str, desc: str, schema: dict) -> MagicMock:  # type: ignore[type-arg]
    t = MagicMock()
    t.name = name
    t.description = desc
    t.inputSchema = schema
    return t


class TestDiscoverTools:
    async def test_returns_tool_info_list(self) -> None:
        tool1 = _make_tool_mock("search", "Search stuff", {"q": "string"})
        tool2 = _make_tool_mock("get_doc", "Get a doc", {})

        session = MagicMock()
        list_result = MagicMock()
        list_result.tools = [tool1, tool2]
        session.list_tools = AsyncMock(return_value=list_result)

        pool = _make_pool_with_session(session)
        svc = _make_service("my-svc")

        result = await discover_tools(pool, svc)  # type: ignore[arg-type]

        assert len(result) == 2
        assert result[0].name == "search"
        assert result[0].description == "Search stuff"
        assert result[0].input_schema == {"q": "string"}
        assert result[0].service_name == "my-svc"
        assert result[1].name == "get_doc"
        assert result[1].service_name == "my-svc"

    async def test_service_name_populated(self) -> None:
        tool = _make_tool_mock("ping", "Ping", {})
        session = MagicMock()
        list_result = MagicMock()
        list_result.tools = [tool]
        session.list_tools = AsyncMock(return_value=list_result)

        pool = _make_pool_with_session(session)
        result = await discover_tools(pool, _make_service("cool-service"))  # type: ignore[arg-type]

        assert result[0].service_name == "cool-service"

    async def test_raises_tool_discovery_error_on_failure(self) -> None:
        session = MagicMock()
        session.list_tools = AsyncMock(side_effect=OSError("connection refused"))

        pool = _make_pool_with_session(session)

        with pytest.raises(ToolDiscoveryError, match="cool-service"):
            await discover_tools(pool, _make_service("cool-service"))  # type: ignore[arg-type]

    async def test_empty_tool_list(self) -> None:
        session = MagicMock()
        list_result = MagicMock()
        list_result.tools = []
        session.list_tools = AsyncMock(return_value=list_result)

        pool = _make_pool_with_session(session)
        result = await discover_tools(pool, _make_service())  # type: ignore[arg-type]

        assert result == []
