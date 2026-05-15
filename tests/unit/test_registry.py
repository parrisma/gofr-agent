"""Tests for app.services.registry.ServiceRegistry."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from app.config import GofrAgentConfig
from app.services import ServiceConfig, ServicesManifest
from app.services.discovery import MCPToolInfo
from app.services.pool import SessionPool
from app.services.registry import ServiceRegistry


def _make_config(**kwargs) -> GofrAgentConfig:  # type: ignore[no-untyped-def]
    defaults = {"require_auth": False, "session_pool_size": 2}
    defaults.update(kwargs)
    return GofrAgentConfig(**defaults)


def _make_svc(name: str = "svc", url: str = "http://svc/mcp") -> ServiceConfig:
    return ServiceConfig(name=name, url=url)


def _make_tools(*names: str, service: str = "svc") -> list[MCPToolInfo]:
    return [
        MCPToolInfo(name=n, description="", input_schema={}, service_name=service)
        for n in names
    ]


def _patch_registry(
    registry: ServiceRegistry, svc: ServiceConfig, tools: list[MCPToolInfo]
) -> None:
    """Patch _register_one on the registry to succeed with given tools."""
    pool = MagicMock(spec=SessionPool)
    pool.stop = AsyncMock()
    pool.start = AsyncMock()

    async def fake_register(s: ServiceConfig) -> list[MCPToolInfo]:
        registry._pools[s.name] = pool
        registry._services[s.name] = s
        registry._tools[s.name] = tools
        return tools

    registry._register_one = fake_register  # type: ignore[method-assign]


class TestLoadManifest:
    async def test_two_services_registered(self) -> None:
        registry = ServiceRegistry(_make_config())
        svc1 = _make_svc("alpha")
        svc2 = _make_svc("beta", "http://beta/mcp")
        tools1 = _make_tools("search", service="alpha")
        tools2 = _make_tools("read", service="beta")

        call_idx = [0]

        async def fake_register(s: ServiceConfig) -> list[MCPToolInfo]:
            if call_idx[0] == 0:
                registry._pools[s.name] = MagicMock(spec=SessionPool)
                registry._services[s.name] = s
                registry._tools[s.name] = tools1
            else:
                registry._pools[s.name] = MagicMock(spec=SessionPool)
                registry._services[s.name] = s
                registry._tools[s.name] = tools2
            call_idx[0] += 1
            return registry._tools[s.name]

        registry._register_one = fake_register  # type: ignore[method-assign]

        manifest = ServicesManifest(services=[svc1, svc2])
        await registry.load_manifest(manifest)

        assert set(registry._pools.keys()) == {"alpha", "beta"}
        assert len(registry.all_tools) == 2

    async def test_failing_service_skipped(self) -> None:
        registry = ServiceRegistry(_make_config())
        svc_ok = _make_svc("good")
        svc_bad = _make_svc("bad", "http://bad/mcp")
        tools_ok = _make_tools("ping", service="good")

        async def fake_register(s: ServiceConfig) -> list[MCPToolInfo]:
            if s.name == "bad":
                raise OSError("connection refused")
            registry._pools[s.name] = MagicMock(spec=SessionPool)
            registry._services[s.name] = s
            registry._tools[s.name] = tools_ok
            return tools_ok

        registry._register_one = fake_register  # type: ignore[method-assign]

        manifest = ServicesManifest(services=[svc_ok, svc_bad])
        await registry.load_manifest(manifest)  # must not raise

        assert "good" in registry._pools
        assert "bad" not in registry._pools

    async def test_disabled_service_skipped(self) -> None:
        registry = ServiceRegistry(_make_config())
        svc = ServiceConfig(name="off", url="http://off/mcp", enabled=False)
        registered: list[str] = []

        async def fake_register(s: ServiceConfig) -> list[MCPToolInfo]:
            registered.append(s.name)
            return []

        registry._register_one = fake_register  # type: ignore[method-assign]

        manifest = ServicesManifest(services=[svc])
        await registry.load_manifest(manifest)

        assert registered == []


class TestRegisterService:
    async def test_adds_to_registry(self) -> None:
        registry = ServiceRegistry(_make_config())
        svc = _make_svc("new")
        tools = _make_tools("alpha", service="new")
        _patch_registry(registry, svc, tools)

        result = await registry.register_service(svc)
        assert result == tools
        assert "new" in registry._pools

    async def test_replaces_existing(self) -> None:
        registry = ServiceRegistry(_make_config())
        svc = _make_svc("svc")

        old_pool = MagicMock(spec=SessionPool)
        old_pool.stop = AsyncMock()
        registry._pools["svc"] = old_pool

        tools = _make_tools("new_tool", service="svc")
        _patch_registry(registry, svc, tools)

        await registry.register_service(svc)
        old_pool.stop.assert_awaited_once()


class TestAllTools:
    async def test_returns_union_across_services(self) -> None:
        registry = ServiceRegistry(_make_config())
        registry._tools = {
            "a": _make_tools("t1", "t2", service="a"),
            "b": _make_tools("t3", service="b"),
        }
        tools = registry.all_tools
        assert len(tools) == 3


class TestShutdown:
    async def test_stops_all_pools(self) -> None:
        registry = ServiceRegistry(_make_config())
        pool1 = MagicMock(spec=SessionPool)
        pool1.stop = AsyncMock()
        pool2 = MagicMock(spec=SessionPool)
        pool2.stop = AsyncMock()
        registry._pools = {"a": pool1, "b": pool2}

        await registry.shutdown()

        pool1.stop.assert_awaited_once()
        pool2.stop.assert_awaited_once()
        assert registry._pools == {}
