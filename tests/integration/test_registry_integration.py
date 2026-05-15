"""Integration tests for ServiceRegistry against the live mock MCP server."""

from __future__ import annotations

import asyncio

from app.config import GofrAgentConfig
from app.services import ServiceConfig, ServicesManifest
from app.services.registry import ServiceRegistry


def _config() -> GofrAgentConfig:
    return GofrAgentConfig(require_auth=False)


def _manifest(url: str) -> ServicesManifest:
    svc = ServiceConfig(name="mock", url=url, description="Mock test service")
    return ServicesManifest(services=[svc])


class TestRegistryIntegration:
    async def test_load_manifest_discovers_tools(self, mock_mcp_url: str) -> None:
        registry = ServiceRegistry(_config())
        await registry.load_manifest(_manifest(mock_mcp_url))
        try:
            tools = registry.all_tools
            names = [t.name for t in tools]
            assert "echo" in names
            assert "add" in names
        finally:
            await registry.shutdown()

    async def test_get_pool_returns_healthy_pool(self, mock_mcp_url: str) -> None:
        registry = ServiceRegistry(_config())
        await registry.load_manifest(_manifest(mock_mcp_url))
        try:
            pool = registry.get_pool("mock")
            assert pool is not None
            assert pool.is_healthy
        finally:
            await registry.shutdown()

    async def test_concurrent_checkouts(self, mock_mcp_url: str) -> None:
        """Pool should allow concurrent tool calls up to pool_size."""
        config = GofrAgentConfig(require_auth=False, session_pool_size=3)
        registry = ServiceRegistry(config)
        await registry.load_manifest(_manifest(mock_mcp_url))
        try:
            pool = registry.get_pool("mock")
            assert pool is not None

            async def _call_echo(msg: str) -> str:
                async with pool.checkout() as session:
                    result = await session.call_tool("echo", {"message": msg})
                return result.content[0].text  # type: ignore[union-attr]

            results = await asyncio.gather(
                _call_echo("a"), _call_echo("b"), _call_echo("c")
            )
            assert set(results) == {"a", "b", "c"}
        finally:
            await registry.shutdown()

    async def test_unknown_service_returns_none(self, mock_mcp_url: str) -> None:
        registry = ServiceRegistry(_config())
        await registry.load_manifest(_manifest(mock_mcp_url))
        try:
            assert registry.get_pool("nonexistent") is None
        finally:
            await registry.shutdown()
