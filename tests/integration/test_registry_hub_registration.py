"""Integration tests for registry-driven hub registration."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from app.config import GofrAgentConfig
from app.services import ServiceConfig, ServicesManifest
from app.services.registry import ServiceRegistry
from tests.fixtures.mcp_services._server import _require_bearer, make_service_server


def _config() -> GofrAgentConfig:
    return GofrAgentConfig(
        require_auth=False,
        hub_enabled=True,
        hub_url="http://gofr-agent:8090/mcp",
        hub_default_ttl_seconds=45,
        hub_max_payload_bytes=131072,
        hub_protocol_version=1,
    )


class _HubRegistrationFixture:
    def __init__(
        self,
        *,
        include_registration_tool: bool = True,
        response: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        self.requests: list[dict[str, Any]] = []
        self.tokens: list[str] = []
        self._response = response or {
            "accepted": True,
            "protocol_version": 1,
            "can_publish": True,
            "can_consume": True,
            "result_types": ["ohlcv_bars"],
            "notes": "ready",
        }
        self._error_message = error_message
        self.mcp = FastMCP("hub-registration-fixture")

        @self.mcp.tool()
        def echo(message: str) -> str:
            return message

        if include_registration_tool:

            @self.mcp.tool(name="_register_results_hub")
            def _register_results_hub(
                protocol_version: int,
                hub_service: str,
                hub_url: str,
                store_tool: str,
                fetch_tool: str,
                describe_tool: str,
                default_ttl_seconds: int,
                max_payload_bytes: int,
                descriptor_kind: str,
            ) -> dict[str, Any]:
                self.tokens.append(_require_bearer())
                self.requests.append(
                    {
                        "protocol_version": protocol_version,
                        "hub_service": hub_service,
                        "hub_url": hub_url,
                        "store_tool": store_tool,
                        "fetch_tool": fetch_tool,
                        "describe_tool": describe_tool,
                        "default_ttl_seconds": default_ttl_seconds,
                        "max_payload_bytes": max_payload_bytes,
                        "descriptor_kind": descriptor_kind,
                    }
                )
                if self._error_message is not None:
                    raise ValueError(self._error_message)
                return self._response


async def _load_registry(
    fixture: _HubRegistrationFixture,
    *,
    service_name: str = "fixture",
    token: str = "fixture-service-token",
) -> tuple[ServiceRegistry, object]:
    host, port, thread = make_service_server(fixture.mcp)
    registry = ServiceRegistry(_config())
    await registry.load_manifest(
        ServicesManifest(
            services=[
                ServiceConfig(
                    name=service_name,
                    url=f"http://{host}:{port}/mcp",
                    token=token,
                )
            ]
        )
    )
    return registry, thread


async def _shutdown_registry(registry: ServiceRegistry, thread: object) -> None:
    await registry.shutdown()
    thread.shutdown()
    thread.join(timeout=5)


class TestRegistryHubRegistration:
    async def test_service_without_registration_tool_registers_normally(self) -> None:
        fixture = _HubRegistrationFixture(include_registration_tool=False)
        registry, thread = await _load_registry(fixture)

        try:
            assert registry.get_pool("fixture") is not None
            assert {tool.name for tool in registry.all_tools} == {"echo"}
            capabilities = registry.service_hub_capabilities("fixture")
            assert capabilities.supports_results_hub is False
            assert capabilities.registration_error is None
        finally:
            await _shutdown_registry(registry, thread)

    async def test_registration_request_records_capabilities_and_uses_service_token(self) -> None:
        fixture = _HubRegistrationFixture()
        registry, thread = await _load_registry(fixture)

        try:
            assert fixture.tokens == ["fixture-service-token"]
            assert fixture.requests == [
                {
                    "protocol_version": 1,
                    "hub_service": "gofr-agent",
                    "hub_url": "http://gofr-agent:8090/mcp",
                    "store_tool": "_store_result",
                    "fetch_tool": "_get_result",
                    "describe_tool": "_describe_result",
                    "default_ttl_seconds": 45,
                    "max_payload_bytes": 131072,
                    "descriptor_kind": "gofr.result_ref",
                }
            ]
            assert "token" not in fixture.requests[0]
            assert "hub_callback_token" not in fixture.requests[0]

            capabilities = registry.service_hub_capabilities("fixture")
            assert capabilities.supports_results_hub is True
            assert capabilities.can_publish_results is True
            assert capabilities.can_consume_results is True
            assert capabilities.result_types == ("ohlcv_bars",)
            assert capabilities.registration_error is None
        finally:
            await _shutdown_registry(registry, thread)

    async def test_rejected_registration_records_error_without_failing_service(self) -> None:
        fixture = _HubRegistrationFixture(
            response={
                "accepted": False,
                "protocol_version": 1,
                "can_publish": False,
                "can_consume": False,
                "result_types": [],
                "notes": "hub disabled",
            }
        )
        registry, thread = await _load_registry(fixture)

        try:
            assert registry.get_pool("fixture") is not None
            capabilities = registry.service_hub_capabilities("fixture")
            assert capabilities.supports_results_hub is False
            assert capabilities.can_publish_results is False
            assert capabilities.can_consume_results is False
            assert capabilities.result_types == ()
            assert capabilities.registration_error == "hub disabled"
        finally:
            await _shutdown_registry(registry, thread)

    async def test_incompatible_protocol_version_records_error(self) -> None:
        fixture = _HubRegistrationFixture(
            response={
                "accepted": True,
                "protocol_version": 2,
                "can_publish": True,
                "can_consume": False,
                "result_types": ["ohlcv_bars"],
                "notes": "newer protocol",
            }
        )
        registry, thread = await _load_registry(fixture)

        try:
            capabilities = registry.service_hub_capabilities("fixture")
            assert capabilities.supports_results_hub is False
            assert capabilities.registration_error is not None
            assert "protocol_version" in capabilities.registration_error
        finally:
            await _shutdown_registry(registry, thread)

    async def test_registration_tool_failure_degrades_that_service_only(self) -> None:
        failing_fixture = _HubRegistrationFixture(error_message="registration blew up")
        healthy_fixture = _HubRegistrationFixture(include_registration_tool=False)

        fail_host, fail_port, fail_thread = make_service_server(failing_fixture.mcp)
        ok_host, ok_port, ok_thread = make_service_server(healthy_fixture.mcp)
        registry = ServiceRegistry(_config())
        await registry.load_manifest(
            ServicesManifest(
                services=[
                    ServiceConfig(
                        name="failing",
                        url=f"http://{fail_host}:{fail_port}/mcp",
                        token="failing-service-token",
                    ),
                    ServiceConfig(
                        name="healthy",
                        url=f"http://{ok_host}:{ok_port}/mcp",
                        token="healthy-service-token",
                    ),
                ]
            )
        )

        try:
            assert registry.get_pool("failing") is not None
            assert registry.get_pool("healthy") is not None

            failing_caps = registry.service_hub_capabilities("failing")
            assert failing_caps.supports_results_hub is False
            assert failing_caps.registration_error is not None
            assert "registration blew up" in failing_caps.registration_error

            healthy_caps = registry.service_hub_capabilities("healthy")
            assert healthy_caps.supports_results_hub is False
            assert healthy_caps.registration_error is None
        finally:
            await registry.shutdown()
            fail_thread.shutdown()
            fail_thread.join(timeout=5)
            ok_thread.shutdown()
            ok_thread.join(timeout=5)
