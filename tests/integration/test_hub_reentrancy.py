"""Integration test for reentrant results-hub callbacks into gofr-agent."""

from __future__ import annotations

import asyncio
import json
import socket

import pytest
from gofr_common.web import AuthHeaderMiddleware
from mcp.server.transport_security import TransportSecuritySettings

from app.agent.agent import GofrAgent
from app.config import GofrAgentConfig
from app.mcp_server.mcp_server import create_mcp_server
from app.services import ServiceConfig, ServicesManifest
from app.services.registry import ServiceHubCapabilities, ServiceRegistry
from app.sessions.store import SessionStore
from tests.fixtures.mcp_services import hub_debug
from tests.fixtures.mcp_services._server import _free_port, _UvicornThread
from tests.helpers.dummy_auth_service import DummyAuthService

_SERVICE_NAME = "hub-fixture"
_SERVICE_TOKEN = "fixture-outbound-token"
_CALLBACK_TOKEN = "dev-fixtures-hub-token"


def _public_host() -> str:
    return socket.gethostbyname(socket.gethostname())


def _allow_host(mcp_app, public_host: str) -> None:  # type: ignore[no-untyped-def]
    mcp_app.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            f"{public_host}:*",
            "127.0.0.1:*",
            "localhost:*",
            "[::1]:*",
        ],
        allowed_origins=[],
    )


class _HubStack:
    def __init__(self, registry: ServiceRegistry, agent_thread: _UvicornThread) -> None:
        self.registry = registry
        self.agent_thread = agent_thread

    async def call_fixture(self, series_id: str) -> tuple[bool, str]:
        pool = self.registry.get_pool(_SERVICE_NAME)
        if pool is None:
            raise AssertionError("hub-fixture pool was not registered")
        async with pool.checkout() as session:
            result = await session.call_tool(
                "debug_reentrant_store_result",
                {"series_id": series_id},
            )
        raw = result.content[0].text if result.content else ""
        return bool(result.isError), raw

    async def shutdown(self) -> None:
        await self.registry.shutdown()
        self.agent_thread.shutdown()
        self.agent_thread.join(timeout=5)
        hub_debug.configure_results_hub(None, None)


async def _start_stack(callback_token: str | None) -> _HubStack:
    public_host = _public_host()
    agent_port = _free_port()
    fixture_port = _free_port()
    hub_url = f"http://{public_host}:{agent_port}/mcp"
    fixture_url = f"http://{public_host}:{fixture_port}/mcp"

    hub_debug.configure_results_hub(hub_url=hub_url, callback_token=callback_token)
    fixture_mcp = hub_debug.build_mcp()
    _allow_host(fixture_mcp, public_host)
    fixture_app = AuthHeaderMiddleware(fixture_mcp.streamable_http_app())
    fixture_thread = _UvicornThread(fixture_app, "0.0.0.0", fixture_port)
    fixture_thread.start()
    fixture_thread.wait_ready()

    config = GofrAgentConfig(
        llm_model="test",
        session_pool_size=5,
        hub_enabled=True,
        hub_url=hub_url,
        hub_default_ttl_seconds=30,
        hub_max_payload_bytes=65536,
        hub_max_results=32,
    )
    registry = ServiceRegistry(config)
    await registry.load_manifest(
        ServicesManifest(
            services=[
                ServiceConfig(
                    name=_SERVICE_NAME,
                    url=fixture_url,
                    token=_SERVICE_TOKEN,
                    hub_callback_token=_CALLBACK_TOKEN,
                )
            ]
        )
    )
    registry.record_hub_capabilities(
        _SERVICE_NAME,
        ServiceHubCapabilities(
            supports_results_hub=True,
            can_publish_results=True,
            can_consume_results=False,
            result_types=("ohlcv_bars",),
        ),
    )

    auth_service = DummyAuthService()
    agent = GofrAgent(config, registry, auth_service)
    agent.build()
    session_store = SessionStore(ttl_minutes=60)
    mcp = create_mcp_server(config, registry, agent, session_store, auth_service)
    _allow_host(mcp, public_host)
    agent_app = AuthHeaderMiddleware(mcp.streamable_http_app())
    agent_thread = _UvicornThread(agent_app, "0.0.0.0", agent_port)
    agent_thread.start()
    agent_thread.wait_ready()

    stack = _HubStack(registry, agent_thread)
    stack.fixture_thread = fixture_thread  # type: ignore[attr-defined]
    return stack


@pytest.fixture()
async def hub_stack() -> _HubStack:
    stack = await _start_stack(_CALLBACK_TOKEN)
    yield stack
    fixture_thread = stack.fixture_thread  # type: ignore[attr-defined]
    await stack.shutdown()
    fixture_thread.shutdown()
    fixture_thread.join(timeout=5)


class TestHubReentrancy:
    async def test_reentrant_store_returns_descriptor_only(self, hub_stack: _HubStack) -> None:
        is_error, raw = await hub_stack.call_fixture("series-1")

        assert is_error is False, raw
        assert "reentrant-raw-payload-marker" not in raw

        data = json.loads(raw)
        assert data["kind"] == "gofr.result_ref"
        assert data["version"] == 1
        assert data["hub_service"] == "gofr-agent"
        assert data["result_guid"]

    async def test_concurrent_reentrant_store_calls_produce_unique_guids(
        self,
        hub_stack: _HubStack,
    ) -> None:
        start = asyncio.get_running_loop().time()

        results = await asyncio.gather(
            *(hub_stack.call_fixture(f"series-{index}") for index in range(5))
        )

        elapsed = asyncio.get_running_loop().time() - start
        assert elapsed < 5

        descriptors = [json.loads(raw) for is_error, raw in results if not is_error]
        assert len(descriptors) == 5
        assert len({descriptor["result_guid"] for descriptor in descriptors}) == 5

    async def test_missing_callback_token_surfaces_hub_auth_error(self) -> None:
        stack = await _start_stack(None)
        fixture_thread = stack.fixture_thread  # type: ignore[attr-defined]
        try:
            is_error, raw = await stack.call_fixture("missing-token")
            assert is_error is True
            assert "hub.unauthorised" in raw
        finally:
            await stack.shutdown()
            fixture_thread.shutdown()
            fixture_thread.join(timeout=5)
