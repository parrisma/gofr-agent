"""Integration tests for hub-backed OHLCV production in the instruments fixture."""

from __future__ import annotations

import asyncio
import importlib
import json
import socket

import httpx
import pytest
from gofr_common.web import AuthHeaderMiddleware
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.agent.agent import GofrAgent
from app.config import GofrAgentConfig
from app.mcp_server.mcp_server import create_mcp_server
from app.services import ServiceConfig, ServicesManifest
from app.services.registry import ServiceRegistry
from app.sessions.store import SessionStore
from app.transport_security import apply_transport_security
from tests.fixtures.mcp_services import instruments
from tests.fixtures.mcp_services._server import _UvicornThread, make_service_server
from tests.helpers.dummy_auth_service import DummyAuthService
from tests.integration.conftest import AUTH_HEADERS
from tests.integration.mock_mcp_server import _free_port

_SERVICE_NAME = "instruments"
_SERVICE_TOKEN = "fixture-outbound-token"
_CALLBACK_TOKEN = "dev-fixtures-hub-token"


def _public_host() -> str:
    return socket.gethostbyname(socket.gethostname())


def _allow_host(mcp_app, public_host: str) -> None:  # type: ignore[no-untyped-def]
    apply_transport_security(
        mcp_app,
        GofrAgentConfig(
            mcp_allowed_hosts=[
                f"{public_host}:*",
                "127.0.0.1:*",
                "localhost:*",
                "[::1]:*",
            ]
        ),
    )


async def _call_tool(
    url: str,
    tool: str,
    arguments: dict,
    *,
    headers: dict[str, str],
) -> tuple[bool, str]:
    async with (
        httpx.AsyncClient(headers=headers) as http_client,
        streamable_http_client(url, http_client=http_client) as (read, write, _),
        ClientSession(read, write) as client,
    ):
        await client.initialize()
        result = await client.call_tool(tool, arguments)
    raw = result.content[0].text if result.content else ""
    return bool(result.isError), raw


class _InstrumentHubStack:
    def __init__(
        self,
        *,
        fixture_module,
        registry: ServiceRegistry,
        agent_thread: _UvicornThread,
    ) -> None:
        self.fixture_module = fixture_module
        self.registry = registry
        self.agent_thread = agent_thread
        self.instruments_url = ""
        self.hub_url = ""
        self.local_hub_url = ""
        self.instrument_thread: _UvicornThread | None = None

    async def shutdown(self) -> None:
        await self.registry.shutdown()
        self.agent_thread.shutdown()
        self.agent_thread.join(timeout=5)
        if self.instrument_thread is not None:
            self.instrument_thread.shutdown()
            self.instrument_thread.join(timeout=5)
        self.fixture_module.reset_results_hub_state()


async def _start_stack(
    monkeypatch: pytest.MonkeyPatch,
    *,
    callback_token: str | None = _CALLBACK_TOKEN,
    hub_max_payload_bytes: int = 65536,
) -> _InstrumentHubStack:
    public_host = _public_host()
    agent_port = _free_port()
    hub_url = f"http://{public_host}:{agent_port}/mcp"
    local_hub_url = f"http://127.0.0.1:{agent_port}/mcp"
    fixture_module = importlib.reload(instruments)

    if callback_token is None:
        monkeypatch.delenv("GOFR_FIXTURES_HUB_CALLBACK_TOKEN", raising=False)
    else:
        monkeypatch.setenv("GOFR_FIXTURES_HUB_CALLBACK_TOKEN", callback_token)
    fixture_module.reset_results_hub_state()

    instruments_host, instruments_port, instrument_thread = make_service_server(fixture_module.mcp)
    instruments_url = f"http://{instruments_host}:{instruments_port}/mcp"

    config = GofrAgentConfig(
        llm_model="test",
        session_pool_size=3,
        hub_enabled=True,
        hub_url=hub_url,
        hub_default_ttl_seconds=30,
        hub_max_payload_bytes=hub_max_payload_bytes,
        hub_max_results=32,
    )
    registry = ServiceRegistry(config)
    await registry.load_manifest(
        ServicesManifest(
            services=[
                ServiceConfig(
                    name=_SERVICE_NAME,
                    url=instruments_url,
                    token=_SERVICE_TOKEN,
                    hub_callback_token=_CALLBACK_TOKEN,
                )
            ]
        )
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
    await _wait_for_hub(hub_url)

    stack = _InstrumentHubStack(
        fixture_module=fixture_module,
        registry=registry,
        agent_thread=agent_thread,
    )
    stack.hub_url = hub_url
    stack.local_hub_url = local_hub_url
    stack.instruments_url = instruments_url
    stack.instrument_thread = instrument_thread
    return stack


async def _wait_for_hub(url: str) -> None:
    headers = {"Authorization": "Bearer dev-admin-token"}
    for _ in range(20):
        try:
            is_error, raw = await _call_tool(url, "ping", {}, headers=headers)
            if is_error is False and raw:
                return
        except Exception:
            pass
        await asyncio.sleep(0.1)
    raise RuntimeError(f"Hub did not become reachable at {url}")


@pytest.mark.asyncio
class TestInstrumentHubIntegration:
    async def test_get_ohlcv_history_returns_descriptor_when_hub_registered(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        stack = await _start_stack(monkeypatch)

        try:
            is_error, raw = await _call_tool(
                stack.instruments_url,
                "get_ohlcv_history",
                {"ticker": "MSFT", "from_date": "2026-02-01", "to_date": "2026-02-28"},
                headers=AUTH_HEADERS,
            )

            assert is_error is False, raw
            assert '"close":' not in raw
            data = json.loads(raw)
            assert data["kind"] == "gofr.result_ref"
            assert data["version"] == 1
            assert data["hub_service"] == "gofr-agent"
            assert data["result_guid"]
        finally:
            await stack.shutdown()

    async def test_hub_describe_returns_authoritative_metadata_for_descriptor(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        stack = await _start_stack(monkeypatch)

        try:
            is_error, raw = await _call_tool(
                stack.instruments_url,
                "get_ohlcv_history",
                {"ticker": "MSFT", "from_date": "2026-02-01", "to_date": "2026-02-28"},
                headers=AUTH_HEADERS,
            )
            assert is_error is False, raw
            descriptor = json.loads(raw)

            describe_headers = {"Authorization": f"Bearer {_CALLBACK_TOKEN}"}
            describe_error, describe_raw = await _call_tool(
                stack.local_hub_url,
                "_describe_result",
                {
                    "protocol_version": 1,
                    "result_guid": descriptor["result_guid"],
                    "hub_service": "gofr-agent",
                    "expected_result_type": "ohlcv_bars",
                    "expected_schema_id": "gofr.ohlcv_bars.v1",
                },
                headers=describe_headers,
            )

            assert describe_error is False, describe_raw
            metadata = json.loads(describe_raw)["metadata"]
            assert metadata["result_type"] == "ohlcv_bars"
            assert metadata["schema_id"] == "gofr.ohlcv_bars.v1"
            assert metadata["producer_service"] == "instruments"
            assert metadata["producer_tool"] == "get_ohlcv_history"
            assert metadata["payload_bytes"] > 0
        finally:
            await stack.shutdown()

    async def test_hub_oversize_rejection_surfaces_through_producer(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        stack = await _start_stack(monkeypatch, hub_max_payload_bytes=10)

        try:
            is_error, raw = await _call_tool(
                stack.instruments_url,
                "get_ohlcv_history",
                {"ticker": "MSFT", "from_date": "2026-02-01", "to_date": "2026-02-28"},
                headers=AUTH_HEADERS,
            )

            assert is_error is True
            assert "hub.oversized_result" in raw
        finally:
            await stack.shutdown()

    async def test_missing_callback_token_surfaces_hub_auth_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        stack = await _start_stack(monkeypatch, callback_token=None)

        try:
            is_error, raw = await _call_tool(
                stack.instruments_url,
                "get_ohlcv_history",
                {"ticker": "MSFT", "from_date": "2026-02-01", "to_date": "2026-02-28"},
                headers=AUTH_HEADERS,
            )

            assert is_error is True
            assert "hub.unauthorised" in raw
        finally:
            await stack.shutdown()
