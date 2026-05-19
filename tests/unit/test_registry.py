"""Tests for app.services.registry.ServiceRegistry."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import GofrAgentConfig
from app.exceptions import ServiceRegistrationPolicyError
from app.services import ServiceConfig, ServicesManifest
from app.services.discovery import MCPToolInfo
from app.services.pool import SessionPool
from app.services.registry import ServiceHubCapabilities, ServiceRegistry


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
        registry = ServiceRegistry(
            _make_config(dynamic_registration_enabled=True, allowed_service_hosts=["*"])
        )
        svc = _make_svc("new")
        tools = _make_tools("alpha", service="new")
        _patch_registry(registry, svc, tools)

        result = await registry.register_service(svc)
        assert result == tools
        assert "new" in registry._pools

    async def test_replaces_existing(self) -> None:
        registry = ServiceRegistry(
            _make_config(dynamic_registration_enabled=True, allowed_service_hosts=["*"])
        )
        svc = _make_svc("svc")

        old_pool = MagicMock(spec=SessionPool)
        old_pool.stop = AsyncMock()
        registry._pools["svc"] = old_pool

        tools = _make_tools("new_tool", service="svc")
        _patch_registry(registry, svc, tools)

        await registry.register_service(svc)
        old_pool.stop.assert_awaited_once()

    async def test_disabled_dynamic_registration_fails_early(self) -> None:
        registry = ServiceRegistry(_make_config(dynamic_registration_enabled=False))

        with pytest.raises(ServiceRegistrationPolicyError, match="disabled"):
            await registry.register_service(_make_svc("new"))

    async def test_disallowed_host_fails_before_pool_creation(self) -> None:
        registry = ServiceRegistry(
            _make_config(dynamic_registration_enabled=True, allowed_service_hosts=["gofr-*"])
        )

        with pytest.raises(ServiceRegistrationPolicyError, match="allowed_service_hosts"):
            await registry.register_service(_make_svc("blocked", "http://blocked-host/mcp"))

    async def test_allowed_host_probes_discovery_before_success(self, monkeypatch) -> None:
        registry = ServiceRegistry(
            _make_config(dynamic_registration_enabled=True, allowed_service_hosts=["gofr-*"])
        )
        svc = _make_svc("mock", "http://gofr-service/mcp")
        tools = _make_tools("alpha", service="mock")
        pool = MagicMock(spec=SessionPool)
        pool.start = AsyncMock()
        pool.stop = AsyncMock()
        pool.is_healthy = True

        session_pool_ctor = MagicMock(return_value=pool)
        monkeypatch.setattr("app.services.registry.SessionPool", session_pool_ctor)
        discover = AsyncMock(return_value=tools)
        monkeypatch.setattr("app.services.registry.discover_tools", discover)

        result = await registry.register_service(svc)

        assert result == tools
        session_pool_ctor.assert_called_once()
        pool.start.assert_awaited_once()
        discover.assert_awaited_once_with(pool, svc)

    async def test_failed_registration_records_failed_service_state(self, monkeypatch) -> None:
        registry = ServiceRegistry(
            _make_config(dynamic_registration_enabled=True, allowed_service_hosts=["gofr-*"])
        )
        svc = _make_svc("mock", "http://gofr-service/mcp")
        pool = MagicMock(spec=SessionPool)
        pool.start = AsyncMock()
        pool.stop = AsyncMock()
        pool.is_healthy = False

        monkeypatch.setattr("app.services.registry.SessionPool", MagicMock(return_value=pool))
        monkeypatch.setattr(
            "app.services.registry.discover_tools",
            AsyncMock(side_effect=RuntimeError("probe failed")),
        )

        with pytest.raises(RuntimeError, match="probe failed"):
            await registry.register_service(svc)

        assert registry.service_status("mock") == "failed"
        assert registry.service_error("mock") == "probe failed"

    async def test_successful_registration_logs_hub_capabilities(self, monkeypatch) -> None:
        registry = ServiceRegistry(
            _make_config(
                dynamic_registration_enabled=True,
                allowed_service_hosts=["*"],
                hub_enabled=True,
                hub_url="http://gofr-agent:8090/mcp",
            )
        )
        svc = ServiceConfig(
            name="analytics",
            url="http://analytics/mcp",
            hub_callback_token="dev-fixtures-hub-token",
        )
        pool = MagicMock(spec=SessionPool)
        pool.start = AsyncMock()
        pool.stop = AsyncMock()
        pool.is_healthy = True

        monkeypatch.setattr("app.services.registry.SessionPool", MagicMock(return_value=pool))
        monkeypatch.setattr(
            "app.services.registry.discover_tools",
            AsyncMock(
                return_value=[
                    MCPToolInfo(
                        name="_register_results_hub",
                        description="",
                        input_schema={},
                        service_name="analytics",
                    ),
                    MCPToolInfo(
                        name="simple_return",
                        description="",
                        input_schema={},
                        service_name="analytics",
                    ),
                ]
            ),
        )
        monkeypatch.setattr(
            registry,
            "_register_results_hub",
            AsyncMock(
                return_value=ServiceHubCapabilities(
                    supports_results_hub=True,
                    can_publish_results=True,
                    can_consume_results=True,
                    result_types=("ohlcv_bars",),
                )
            ),
        )

        with pytest.MonkeyPatch.context() as _:
            pass

        info_log = MagicMock()
        monkeypatch.setattr("app.services.registry.logger.info", info_log)

        await registry.register_service(svc)

        registered_calls = [
            call for call in info_log.call_args_list if call.args[0] == "Registered service"
        ]
        assert registered_calls
        fields = registered_calls[-1].kwargs
        assert fields["service"] == "analytics"
        assert fields["hub_tool_advertised"] is True
        assert fields["hub_callback_configured"] is True
        assert fields["supports_results_hub"] is True
        assert fields["can_publish_results"] is True
        assert fields["can_consume_results"] is True
        assert fields["result_types"] == ["ohlcv_bars"]

    async def test_hub_tool_warning_when_agent_hub_disabled(self, monkeypatch) -> None:
        registry = ServiceRegistry(
            _make_config(dynamic_registration_enabled=True, allowed_service_hosts=["*"])
        )
        svc = ServiceConfig(
            name="analytics",
            url="http://analytics/mcp",
            hub_callback_token="dev-fixtures-hub-token",
        )
        pool = MagicMock(spec=SessionPool)
        pool.start = AsyncMock()
        pool.stop = AsyncMock()
        pool.is_healthy = True

        monkeypatch.setattr("app.services.registry.SessionPool", MagicMock(return_value=pool))
        monkeypatch.setattr(
            "app.services.registry.discover_tools",
            AsyncMock(
                return_value=[
                    MCPToolInfo(
                        name="_register_results_hub",
                        description="",
                        input_schema={},
                        service_name="analytics",
                    ),
                ]
            ),
        )

        warning_log = MagicMock()
        monkeypatch.setattr("app.services.registry.logger.warning", warning_log)

        await registry.register_service(svc)

        warning_calls = [
            call
            for call in warning_log.call_args_list
            if call.args[0] == "Service advertises results hub but agent hub is disabled"
        ]
        assert warning_calls
        fields = warning_calls[-1].kwargs
        assert fields["service"] == "analytics"
        assert fields["hub_callback_configured"] is True


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
        registry._services = {"a": _make_svc("a"), "b": _make_svc("b")}
        registry._tools = {"a": _make_tools("echo", service="a")}
        registry._hub_capabilities = {"a": MagicMock(), "b": MagicMock()}

        await registry.shutdown()

        pool1.stop.assert_awaited_once()
        pool2.stop.assert_awaited_once()
        assert registry._pools == {}
        assert registry._services == {}
        assert registry._tools == {}
        assert registry._hub_capabilities == {}
