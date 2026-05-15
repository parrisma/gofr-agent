"""Integration tests: verify the mock MCP server fixture itself."""

from __future__ import annotations

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


class TestMockMCPServer:
    async def test_server_is_reachable(self, mock_mcp_url: str) -> None:
        async with (
            streamablehttp_client(mock_mcp_url) as (read, write, _),
            ClientSession(read, write) as client,
        ):
            await client.initialize()
            tools = await client.list_tools()
        names = [t.name for t in tools.tools]
        assert "echo" in names
        assert "add" in names

    async def test_echo_tool(self, mock_mcp_url: str) -> None:
        async with (
            streamablehttp_client(mock_mcp_url) as (read, write, _),
            ClientSession(read, write) as client,
        ):
            await client.initialize()
            result = await client.call_tool("echo", {"message": "hello"})
        assert any(
            hasattr(c, "text") and c.text == "hello" for c in result.content
        )

    async def test_add_tool(self, mock_mcp_url: str) -> None:
        async with (
            streamablehttp_client(mock_mcp_url) as (read, write, _),
            ClientSession(read, write) as client,
        ):
            await client.initialize()
            result = await client.call_tool("add", {"a": 3.0, "b": 4.0})
        text = result.content[0].text  # type: ignore[union-attr]
        assert float(text) == pytest.approx(7.0)
