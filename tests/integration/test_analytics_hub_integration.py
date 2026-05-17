"""Integration tests for hub-backed analytics descriptor consumption."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import os
import socket

import httpx
import pytest
from gofr_common.web import AuthHeaderMiddleware
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.agent.agent import GofrAgent
from app.auth.permissions import AGENT_HUB_FETCH, AGENT_HUB_STORE
from app.config import GofrAgentConfig
from app.mcp_server.mcp_server import create_mcp_server
from app.services import ServiceConfig, ServicesManifest
from app.services.registry import ServiceRegistry
from app.sessions.store import SessionStore
from app.transport_security import apply_transport_security
from tests.fixtures.mcp_services import analytics, instruments
from tests.fixtures.mcp_services._results_hub import GOFR_FIXTURES_HUB_CALLBACK_TOKEN
from tests.fixtures.mcp_services._server import _UvicornThread, make_service_server
from tests.helpers.dummy_auth_service import DummyAuthService
from tests.integration.conftest import AUTH_HEADERS
from tests.integration.mock_mcp_server import _free_port

_INSTRUMENTS_SERVICE = "instruments"
_ANALYTICS_SERVICE = "analytics"
_INSTRUMENTS_TOKEN = "fixture-outbound-token"
_ANALYTICS_TOKEN = "analytics-outbound-token"
_PRODUCER_CALLBACK_TOKEN = "dev-instruments-hub-token"
_CONSUMER_CALLBACK_TOKEN = "dev-analytics-hub-token"


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


class _HubAuthService(DummyAuthService):
    def authorised_activities(self, token: str) -> str:
        if token in {_PRODUCER_CALLBACK_TOKEN, _CONSUMER_CALLBACK_TOKEN}:
            return f"{AGENT_HUB_STORE},{AGENT_HUB_FETCH}"
        return super().authorised_activities(token)


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


@contextlib.contextmanager
def _hub_callback_token(token: str | None):
    previous = os.environ.get(GOFR_FIXTURES_HUB_CALLBACK_TOKEN)
    if token is None:
        os.environ.pop(GOFR_FIXTURES_HUB_CALLBACK_TOKEN, None)
    else:
        os.environ[GOFR_FIXTURES_HUB_CALLBACK_TOKEN] = token
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(GOFR_FIXTURES_HUB_CALLBACK_TOKEN, None)
        else:
            os.environ[GOFR_FIXTURES_HUB_CALLBACK_TOKEN] = previous


class _AnalyticsHubStack:
    def __init__(
        self,
        *,
        analytics_module,
        instruments_module,
        registry: ServiceRegistry,
        agent_thread: _UvicornThread,
    ) -> None:
        self.analytics_module = analytics_module
        self.instruments_module = instruments_module
        self.registry = registry
        self.agent_thread = agent_thread
        self.analytics_thread: _UvicornThread | None = None
        self.instruments_thread: _UvicornThread | None = None
        self.analytics_url = ""
        self.instruments_url = ""
        self.hub_url = ""
        self.local_hub_url = ""

    async def shutdown(self) -> None:
        await self.registry.shutdown()
        self.agent_thread.shutdown()
        self.agent_thread.join(timeout=5)
        if self.analytics_thread is not None:
            self.analytics_thread.shutdown()
            self.analytics_thread.join(timeout=5)
        if self.instruments_thread is not None:
            self.instruments_thread.shutdown()
            self.instruments_thread.join(timeout=5)
        self.analytics_module.reset_results_hub_state()
        self.instruments_module.reset_results_hub_state()


async def _start_stack() -> _AnalyticsHubStack:
    public_host = _public_host()
    agent_port = _free_port()
    hub_url = f"http://{public_host}:{agent_port}/mcp"
    local_hub_url = f"http://127.0.0.1:{agent_port}/mcp"

    instruments_module = importlib.reload(instruments)
    analytics_module = importlib.reload(analytics)
    instruments_module.reset_results_hub_state()
    analytics_module.reset_results_hub_state()
    instruments_module.configure_results_hub_auth(_PRODUCER_CALLBACK_TOKEN)
    analytics_module.configure_results_hub_auth(_CONSUMER_CALLBACK_TOKEN)

    instruments_host, instruments_port, instruments_thread = make_service_server(
        instruments_module.mcp
    )
    analytics_host, analytics_port, analytics_thread = make_service_server(analytics_module.mcp)

    config = GofrAgentConfig(
        llm_model="test",
        session_pool_size=4,
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
                    name=_INSTRUMENTS_SERVICE,
                    url=f"http://{instruments_host}:{instruments_port}/mcp",
                    token=_INSTRUMENTS_TOKEN,
                    hub_callback_token=_PRODUCER_CALLBACK_TOKEN,
                ),
                ServiceConfig(
                    name=_ANALYTICS_SERVICE,
                    url=f"http://{analytics_host}:{analytics_port}/mcp",
                    token=_ANALYTICS_TOKEN,
                    hub_callback_token=_CONSUMER_CALLBACK_TOKEN,
                ),
            ]
        )
    )

    auth_service = _HubAuthService()
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

    stack = _AnalyticsHubStack(
        analytics_module=analytics_module,
        instruments_module=instruments_module,
        registry=registry,
        agent_thread=agent_thread,
    )
    stack.analytics_thread = analytics_thread
    stack.instruments_thread = instruments_thread
    stack.analytics_url = f"http://{analytics_host}:{analytics_port}/mcp"
    stack.instruments_url = f"http://{instruments_host}:{instruments_port}/mcp"
    stack.hub_url = hub_url
    stack.local_hub_url = local_hub_url
    return stack


async def _get_descriptor(stack: _AnalyticsHubStack) -> dict:
    with _hub_callback_token(_PRODUCER_CALLBACK_TOKEN):
        is_error, raw = await _call_tool(
            stack.instruments_url,
            "get_ohlcv_history",
            {"ticker": "MSFT", "from_date": "2026-02-01", "to_date": "2026-02-28"},
            headers=AUTH_HEADERS,
        )
    assert is_error is False, raw
    return json.loads(raw)


async def _get_payload_from_hub(stack: _AnalyticsHubStack, descriptor: dict) -> list[dict]:
    headers = {"Authorization": f"Bearer {_CONSUMER_CALLBACK_TOKEN}"}
    is_error, raw = await _call_tool(
        stack.local_hub_url,
        "_get_result",
        {
            "protocol_version": 1,
            "result_guid": descriptor["result_guid"],
            "hub_service": descriptor["hub_service"],
            "expected_result_type": "ohlcv_bars",
            "expected_schema_id": "gofr.ohlcv_bars.v1",
        },
        headers=headers,
    )
    assert is_error is False, raw
    return json.loads(raw)["payload"]


@pytest.mark.asyncio
class TestAnalyticsHubIntegration:
    async def test_simple_return_accepts_bars_ref_and_matches_inline(self) -> None:
        stack = await _start_stack()

        try:
            descriptor = await _get_descriptor(stack)
            payload = await _get_payload_from_hub(stack, descriptor)

            with _hub_callback_token(_CONSUMER_CALLBACK_TOKEN):
                descriptor_error, descriptor_raw = await _call_tool(
                    stack.analytics_url,
                    "simple_return",
                    {"ticker": "MSFT", "bars_ref": descriptor},
                    headers=AUTH_HEADERS,
                )
            inline_error, inline_raw = await _call_tool(
                stack.analytics_url,
                "simple_return",
                {"ticker": "MSFT", "bars": payload},
                headers=AUTH_HEADERS,
            )

            assert descriptor_error is False, descriptor_raw
            assert inline_error is False, inline_raw
            assert json.loads(descriptor_raw) == json.loads(inline_raw)
        finally:
            await stack.shutdown()

    async def test_historical_volatility_and_max_drawdown_accept_bars_ref(self) -> None:
        stack = await _start_stack()

        try:
            descriptor = await _get_descriptor(stack)

            with _hub_callback_token(_CONSUMER_CALLBACK_TOKEN):
                vol_error, vol_raw = await _call_tool(
                    stack.analytics_url,
                    "historical_volatility",
                    {"ticker": "MSFT", "bars_ref": descriptor, "window": 5},
                    headers=AUTH_HEADERS,
                )
                dd_error, dd_raw = await _call_tool(
                    stack.analytics_url,
                    "max_drawdown",
                    {"ticker": "MSFT", "bars_ref": descriptor},
                    headers=AUTH_HEADERS,
                )

            assert vol_error is False, vol_raw
            assert dd_error is False, dd_raw
            assert json.loads(vol_raw)["annualised_vol"] is not None
            assert "max_drawdown_pct" in json.loads(dd_raw)
        finally:
            await stack.shutdown()

    async def test_tampered_descriptor_advisory_fields_do_not_change_behaviour(self) -> None:
        stack = await _start_stack()

        try:
            descriptor = await _get_descriptor(stack)
            tampered = dict(descriptor)
            tampered["result_type"] = "tampered_type"
            tampered["schema_id"] = "tampered.schema"
            tampered["producer_service"] = "tampered-service"

            with _hub_callback_token(_CONSUMER_CALLBACK_TOKEN):
                original_error, original_raw = await _call_tool(
                    stack.analytics_url,
                    "simple_return",
                    {"ticker": "MSFT", "bars_ref": descriptor},
                    headers=AUTH_HEADERS,
                )
                tampered_error, tampered_raw = await _call_tool(
                    stack.analytics_url,
                    "simple_return",
                    {"ticker": "MSFT", "bars_ref": tampered},
                    headers=AUTH_HEADERS,
                )

            assert original_error is False, original_raw
            assert tampered_error is False, tampered_raw
            assert json.loads(original_raw) == json.loads(tampered_raw)
        finally:
            await stack.shutdown()

    async def test_malformed_descriptor_kind_is_rejected_before_hub_fetch(self) -> None:
        stack = await _start_stack()

        try:
            bad_descriptor = {
                "kind": "not-a-gofr-ref",
                "version": 1,
                "result_guid": "missing-result",
                "hub_service": "gofr-agent",
            }
            with _hub_callback_token(_CONSUMER_CALLBACK_TOKEN):
                is_error, raw = await _call_tool(
                    stack.analytics_url,
                    "simple_return",
                    {"ticker": "MSFT", "bars_ref": bad_descriptor},
                    headers=AUTH_HEADERS,
                )

            assert is_error is True
            assert "gofr.result_ref" in raw or "validation" in raw.lower()
            assert "hub.unauthorised" not in raw
            assert "connect" not in raw.lower()
        finally:
            await stack.shutdown()
