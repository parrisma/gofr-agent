"""Integration tests for ServiceRegistry against the live mock MCP server."""

from __future__ import annotations

import asyncio

import pytest

from app.config import GofrAgentConfig
from app.exceptions import ServiceRegistrationPolicyError
from app.services import ServiceConfig, ServicesManifest
from app.services.registry import ServiceRegistry


def _config() -> GofrAgentConfig:
    return GofrAgentConfig(require_auth=False)


def _manifest(url: str) -> ServicesManifest:
    svc = ServiceConfig(name="mock", url=url, description="Mock test service")
    return ServicesManifest(services=[svc])


async def _shutdown_registry(registry: ServiceRegistry) -> None:
    await registry.shutdown()


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
            await _shutdown_registry(registry)

    async def test_get_pool_returns_healthy_pool(self, mock_mcp_url: str) -> None:
        registry = ServiceRegistry(_config())
        await registry.load_manifest(_manifest(mock_mcp_url))
        try:
            pool = registry.get_pool("mock")
            assert pool is not None
            assert pool.is_healthy
        finally:
            await _shutdown_registry(registry)

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
            await _shutdown_registry(registry)

    async def test_unknown_service_returns_none(self, mock_mcp_url: str) -> None:
        registry = ServiceRegistry(_config())
        await registry.load_manifest(_manifest(mock_mcp_url))
        try:
            assert registry.get_pool("nonexistent") is None
        finally:
            await _shutdown_registry(registry)

    async def test_dynamic_registration_discovers_tools_when_host_allowed(
        self, mock_mcp_url: str
    ) -> None:
        registry = ServiceRegistry(
            GofrAgentConfig(
                dynamic_registration_enabled=True,
                allowed_service_hosts=["127.0.0.1"],
            )
        )
        try:
            tools = await registry.register_service(
                ServiceConfig(name="mock", url=mock_mcp_url, description="Mock test service")
            )
            assert {tool.name for tool in tools} >= {"echo", "add"}
        finally:
            await _shutdown_registry(registry)

    async def test_dynamic_registration_rejects_disallowed_host(self) -> None:
        registry = ServiceRegistry(
            GofrAgentConfig(
                dynamic_registration_enabled=True,
                allowed_service_hosts=["gofr-*"],
            )
        )
        with pytest.raises(ServiceRegistrationPolicyError, match="allowed_service_hosts"):
            await registry.register_service(
                ServiceConfig(name="mock", url="http://127.0.0.1:8199/mcp")
            )
