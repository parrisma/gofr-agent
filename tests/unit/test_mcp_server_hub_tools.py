"""Tests for hub MCP tools and reserved-tool redaction."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from gofr_common.web import reset_auth_header_context, set_auth_header_context
from mcp import McpError

from app.agent.agent import GofrAgent
from app.auth.permissions import AGENT_ASK, AGENT_HUB_FETCH, AGENT_HUB_STORE
from app.config import GofrAgentConfig
from app.hub.auth import (
    HUB_CALLBACK_TOKEN_AUDIENCE,
    HUB_CALLBACK_TOKEN_ISSUER,
    HUB_CALLBACK_TOKEN_TYPE,
    mint_hub_callback_token,
)
from app.hub.clock import Clock
from app.hub.store import ResultStore
from app.mcp_server.mcp_server import create_mcp_server
from app.services import ServiceConfig
from app.services.discovery import MCPToolInfo
from app.services.registry import ServiceHubCapabilities, ServiceRegistry
from app.sessions.store import SessionStore

_SIGNED_HUB_SECRET = "unit-hub-secret"  # pragma: allowlist secret
class _AuthMap:
    def __init__(self, token_map: dict[str, tuple[str, ...]]) -> None:
        self._token_map = token_map

    def authorised_activities(self, token: str) -> str:
        return ",".join(self._token_map.get(token, ()))


class _FakeClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def utcnow(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._now.timestamp()

    def advance(self, seconds: int) -> None:
        self._now += timedelta(seconds=seconds)


@contextmanager
def _auth_context(token: str | None) -> Generator[None, None, None]:
    raw = f"Bearer {token}" if token else ""
    ctx_token = set_auth_header_context(raw)
    try:
        yield
    finally:
        reset_auth_header_context(ctx_token)


def _make_config(**overrides) -> GofrAgentConfig:  # type: ignore[no-untyped-def]
    defaults = {"hub_default_ttl_seconds": 60, "hub_max_payload_bytes": 2048}
    defaults.update(overrides)
    return GofrAgentConfig(**defaults)


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _sign_hub_claims(claims: dict[str, object]) -> str:
    header = {"alg": "HS256", "typ": HUB_CALLBACK_TOKEN_TYPE}
    encoded_header = _base64url_encode(
        json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    encoded_payload = _base64url_encode(
        json.dumps(claims, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    signing_input = f"{encoded_header}.{encoded_payload}"
    signature = _base64url_encode(
        hmac.new(
            _SIGNED_HUB_SECRET.encode("utf-8"),
            signing_input.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    )
    return f"{signing_input}.{signature}"


def _signed_callback_token(
    *,
    service: str,
    session_namespace: str,
    allowed_operations: tuple[str, ...],
    allowed_result_types: tuple[str, ...] = ("ohlcv_bars",),
    ttl_seconds: int = 300,
    now: datetime | None = None,
    token_id: str | None = None,
) -> str:
    return mint_hub_callback_token(
        secret=_SIGNED_HUB_SECRET,
        service=service,
        session_namespace=session_namespace,
        allowed_operations=allowed_operations,
        allowed_result_types=allowed_result_types,
        ttl_seconds=ttl_seconds,
        now=now or datetime.now(UTC),
        token_id=token_id,
    )


def _signed_callback_claims(
    *,
    service: str = "publisher",
    session_namespace: str = "session-a",
    ops: tuple[str, ...] = ("store",),
    result_types: tuple[str, ...] = ("ohlcv_bars",),
    ttl_seconds: int = 300,
    now: datetime | None = None,
    token_id: str = "signed-token",
    **overrides: object,
) -> str:
    current_time = now or datetime.now(UTC)
    issued_at = int(current_time.timestamp())
    claims: dict[str, object] = {
        "iss": HUB_CALLBACK_TOKEN_ISSUER,
        "aud": HUB_CALLBACK_TOKEN_AUDIENCE,
        "typ": HUB_CALLBACK_TOKEN_TYPE,
        "service": service,
        "session_namespace": session_namespace,
        "ops": ops,
        "result_types": result_types,
        "iat": issued_at,
        "nbf": issued_at,
        "exp": issued_at + ttl_seconds,
        "jti": token_id,
    }
    claims.update(overrides)
    return _sign_hub_claims(claims)


def _make_registry(
    *,
    services: list[ServiceConfig],
    capabilities: dict[str, ServiceHubCapabilities],
    tools: list[MCPToolInfo] | None = None,
) -> MagicMock:
    registry = MagicMock(spec=ServiceRegistry)
    registry.all_service_configs = services
    registry.all_tools = tools or []
    registry.all_pools = {}
    registry.service_status = MagicMock(return_value="healthy")
    registry.service_error = MagicMock(return_value=None)
    registry.service_hub_capabilities = MagicMock(
        side_effect=lambda name: capabilities.get(name, ServiceHubCapabilities())
    )
    registry.register_service = AsyncMock(return_value=[])
    return registry


def _make_agent() -> MagicMock:
    agent = MagicMock(spec=GofrAgent)
    agent.run = AsyncMock()
    agent.rebuild = MagicMock()
    return agent


async def _call_tool(mcp, tool_name: str, **kwargs):  # type: ignore[return, no-untyped-def]
    tool = mcp._tool_manager._tools[tool_name]
    return await tool.fn(**kwargs)


def _store_args(**overrides):  # type: ignore[no-untyped-def]
    payload = [{"date": "2026-05-16", "close": 100.0}]
    defaults = {
        "protocol_version": 1,
        "producer_service": "publisher",
        "producer_tool": "publish_prices",
        "result_type": "ohlcv_bars",
        "schema_id": "gofr.ohlcv_bars.v1",
        "payload": payload,
        "summary": "one bar",
        "source_args": {"ticker": "AAPL"},
        "ttl_seconds": 30,
    }
    defaults.update(overrides)
    return defaults


class TestHubTools:
    async def test_signed_callback_tokens_are_session_scoped(self) -> None:
        config = _make_config(hub_callback_token_secret=_SIGNED_HUB_SECRET)
        registry = _make_registry(
            services=[
                ServiceConfig(name="publisher", url="http://publisher/mcp"),
                ServiceConfig(name="consumer", url="http://consumer/mcp"),
            ],
            capabilities={
                "publisher": ServiceHubCapabilities(
                    supports_results_hub=True,
                    can_publish_results=True,
                    result_types=("ohlcv_bars",),
                ),
                "consumer": ServiceHubCapabilities(
                    supports_results_hub=True,
                    can_consume_results=True,
                    result_types=("ohlcv_bars",),
                ),
            },
        )
        store = ResultStore(config)
        mcp = create_mcp_server(
            config,
            registry,
            _make_agent(),
            SessionStore(),
            _AuthMap({}),
            store,
        )

        publisher_token = _signed_callback_token(
            service="publisher",
            session_namespace="session-a",
            allowed_operations=("store",),
            token_id="publisher-session-a",
        )
        consumer_token_a = _signed_callback_token(
            service="consumer",
            session_namespace="session-a",
            allowed_operations=("get", "describe"),
            token_id="consumer-session-a",
        )
        consumer_token_b = _signed_callback_token(
            service="consumer",
            session_namespace="session-b",
            allowed_operations=("get", "describe"),
            token_id="consumer-session-b",
        )

        with _auth_context(publisher_token):
            stored = await _call_tool(mcp, "_store_result", **_store_args())

        with _auth_context(consumer_token_a):
            fetched = await _call_tool(
                mcp,
                "_get_result",
                protocol_version=1,
                result_guid=stored["descriptor"]["result_guid"],
                hub_service="gofr-agent",
                expected_result_type="ohlcv_bars",
                expected_schema_id="gofr.ohlcv_bars.v1",
            )

        with _auth_context(consumer_token_a):
            described = await _call_tool(
                mcp,
                "_describe_result",
                protocol_version=1,
                result_guid=stored["descriptor"]["result_guid"],
                hub_service="gofr-agent",
                expected_result_type="ohlcv_bars",
                expected_schema_id="gofr.ohlcv_bars.v1",
            )

        assert fetched["payload"] == [{"date": "2026-05-16", "close": 100.0}]
        assert described["metadata"]["result_guid"] == stored["descriptor"]["result_guid"]

        with _auth_context(consumer_token_b), pytest.raises(McpError) as exc_info:
            await _call_tool(
                mcp,
                "_get_result",
                protocol_version=1,
                result_guid=stored["descriptor"]["result_guid"],
                hub_service="gofr-agent",
                expected_result_type="ohlcv_bars",
                expected_schema_id="gofr.ohlcv_bars.v1",
            )

        assert exc_info.value.error.data == {"hub_code": "hub.unknown_result"}

        with _auth_context(consumer_token_b), pytest.raises(McpError) as exc_info:
            await _call_tool(
                mcp,
                "_describe_result",
                protocol_version=1,
                result_guid=stored["descriptor"]["result_guid"],
                hub_service="gofr-agent",
                expected_result_type="ohlcv_bars",
                expected_schema_id="gofr.ohlcv_bars.v1",
            )

        assert exc_info.value.error.data == {"hub_code": "hub.unknown_result"}

    async def test_store_result_rejects_signed_token_with_wrong_audience(self) -> None:
        config = _make_config(hub_callback_token_secret=_SIGNED_HUB_SECRET)
        registry = _make_registry(
            services=[ServiceConfig(name="publisher", url="http://publisher/mcp")],
            capabilities={
                "publisher": ServiceHubCapabilities(
                    supports_results_hub=True,
                    can_publish_results=True,
                    result_types=("ohlcv_bars",),
                )
            },
        )
        mcp = create_mcp_server(
            config,
            registry,
            _make_agent(),
            SessionStore(),
            _AuthMap({}),
            ResultStore(config),
        )

        token = _signed_callback_claims(aud="wrong-audience")

        with _auth_context(token), pytest.raises(McpError) as exc_info:
            await _call_tool(mcp, "_store_result", **_store_args())

        assert exc_info.value.error.data == {"hub_code": "hub.unauthorised"}

    async def test_store_result_rejects_signed_token_for_unregistered_service(self) -> None:
        config = _make_config(hub_callback_token_secret=_SIGNED_HUB_SECRET)
        registry = _make_registry(services=[], capabilities={})
        mcp = create_mcp_server(
            config,
            registry,
            _make_agent(),
            SessionStore(),
            _AuthMap({}),
            ResultStore(config),
        )

        token = _signed_callback_token(
            service="other-service",
            session_namespace="session-a",
            allowed_operations=("store",),
            token_id="other-service",
        )

        with _auth_context(token), pytest.raises(McpError) as exc_info:
            await _call_tool(
                mcp,
                "_store_result",
                **_store_args(producer_service="other-service"),
            )

        assert exc_info.value.error.data == {"hub_code": "hub.unregistered_service"}

    async def test_store_result_rejects_signed_token_with_wrong_operation(self) -> None:
        config = _make_config(hub_callback_token_secret=_SIGNED_HUB_SECRET)
        registry = _make_registry(
            services=[ServiceConfig(name="publisher", url="http://publisher/mcp")],
            capabilities={
                "publisher": ServiceHubCapabilities(
                    supports_results_hub=True,
                    can_publish_results=True,
                    result_types=("ohlcv_bars",),
                )
            },
        )
        mcp = create_mcp_server(
            config,
            registry,
            _make_agent(),
            SessionStore(),
            _AuthMap({}),
            ResultStore(config),
        )

        token = _signed_callback_token(
            service="publisher",
            session_namespace="session-a",
            allowed_operations=("get",),
            token_id="wrong-operation",
        )

        with _auth_context(token), pytest.raises(McpError) as exc_info:
            await _call_tool(mcp, "_store_result", **_store_args())

        assert exc_info.value.error.data == {"hub_code": "hub.unauthorised"}

    async def test_store_result_rejects_expired_signed_token(self) -> None:
        config = _make_config(hub_callback_token_secret=_SIGNED_HUB_SECRET)
        registry = _make_registry(
            services=[ServiceConfig(name="publisher", url="http://publisher/mcp")],
            capabilities={
                "publisher": ServiceHubCapabilities(
                    supports_results_hub=True,
                    can_publish_results=True,
                    result_types=("ohlcv_bars",),
                )
            },
        )
        mcp = create_mcp_server(
            config,
            registry,
            _make_agent(),
            SessionStore(),
            _AuthMap({}),
            ResultStore(config),
        )

        token = _signed_callback_token(
            service="publisher",
            session_namespace="session-a",
            allowed_operations=("store",),
            ttl_seconds=30,
            now=datetime(2000, 1, 1, tzinfo=UTC),
            token_id="expired-token",
        )

        with _auth_context(token), pytest.raises(McpError) as exc_info:
            await _call_tool(mcp, "_store_result", **_store_args())

        assert exc_info.value.error.data == {"hub_code": "hub.unauthorised"}

    async def test_store_result_rejects_signed_token_without_session_scope(self) -> None:
        config = _make_config(hub_callback_token_secret=_SIGNED_HUB_SECRET)
        registry = _make_registry(
            services=[ServiceConfig(name="publisher", url="http://publisher/mcp")],
            capabilities={
                "publisher": ServiceHubCapabilities(
                    supports_results_hub=True,
                    can_publish_results=True,
                    result_types=("ohlcv_bars",),
                )
            },
        )
        mcp = create_mcp_server(
            config,
            registry,
            _make_agent(),
            SessionStore(),
            _AuthMap({}),
            ResultStore(config),
        )

        token = _signed_callback_claims(session_namespace="")

        with _auth_context(token), pytest.raises(McpError) as exc_info:
            await _call_tool(mcp, "_store_result", **_store_args())

        assert exc_info.value.error.data == {"hub_code": "hub.unauthorised"}

    async def test_store_result_accepts_valid_callback_token(self) -> None:
        config = _make_config()
        registry = _make_registry(
            services=[
                ServiceConfig(
                    name="publisher",
                    url="http://publisher/mcp",
                    hub_callback_token="publisher-token",
                )
            ],
            capabilities={
                "publisher": ServiceHubCapabilities(
                    supports_results_hub=True,
                    can_publish_results=True,
                    can_consume_results=True,
                    result_types=("ohlcv_bars",),
                )
            },
        )
        mcp = create_mcp_server(
            config,
            registry,
            _make_agent(),
            SessionStore(),
            _AuthMap({"publisher-token": (AGENT_HUB_STORE, AGENT_HUB_FETCH)}),
            ResultStore(config),
        )

        with _auth_context("publisher-token"):
            result = await _call_tool(mcp, "_store_result", **_store_args())

        assert result["descriptor"]["result_guid"]
        assert result["descriptor"]["result_type"] == "ohlcv_bars"

    async def test_store_result_rejects_ordinary_ask_token(self) -> None:
        config = _make_config()
        registry = _make_registry(services=[], capabilities={})
        mcp = create_mcp_server(
            config,
            registry,
            _make_agent(),
            SessionStore(),
            _AuthMap({"ask-token": (AGENT_ASK,)}),
            ResultStore(config),
        )

        with _auth_context("ask-token"), pytest.raises(McpError) as exc_info:
            await _call_tool(mcp, "_store_result", **_store_args())

        assert exc_info.value.error.data == {"hub_code": "hub.unauthorised"}

    async def test_store_result_rejects_mismatched_producer_service(self) -> None:
        config = _make_config()
        registry = _make_registry(
            services=[
                ServiceConfig(
                    name="publisher",
                    url="http://publisher/mcp",
                    hub_callback_token="publisher-token",
                )
            ],
            capabilities={
                "publisher": ServiceHubCapabilities(
                    supports_results_hub=True,
                    can_publish_results=True,
                    result_types=("ohlcv_bars",),
                )
            },
        )
        mcp = create_mcp_server(
            config,
            registry,
            _make_agent(),
            SessionStore(),
            _AuthMap({"publisher-token": (AGENT_HUB_STORE,)}),
            ResultStore(config),
        )

        with _auth_context("publisher-token"), pytest.raises(McpError) as exc_info:
            await _call_tool(
                mcp,
                "_store_result",
                **_store_args(producer_service="other-service"),
            )

        assert exc_info.value.error.data == {"hub_code": "hub.unregistered_service"}

    async def test_store_result_rejects_unregistered_service_token(self) -> None:
        config = _make_config()
        registry = _make_registry(services=[], capabilities={})
        mcp = create_mcp_server(
            config,
            registry,
            _make_agent(),
            SessionStore(),
            _AuthMap({"orphan-token": (AGENT_HUB_STORE,)}),
            ResultStore(config),
        )

        with _auth_context("orphan-token"), pytest.raises(McpError) as exc_info:
            await _call_tool(mcp, "_store_result", **_store_args())

        assert exc_info.value.error.data == {"hub_code": "hub.unregistered_service"}

    async def test_store_result_rejects_unregistered_result_type(self) -> None:
        config = _make_config()
        registry = _make_registry(
            services=[
                ServiceConfig(
                    name="publisher",
                    url="http://publisher/mcp",
                    hub_callback_token="publisher-token",
                )
            ],
            capabilities={
                "publisher": ServiceHubCapabilities(
                    supports_results_hub=True,
                    can_publish_results=True,
                    result_types=("positions",),
                )
            },
        )
        mcp = create_mcp_server(
            config,
            registry,
            _make_agent(),
            SessionStore(),
            _AuthMap({"publisher-token": (AGENT_HUB_STORE,)}),
            ResultStore(config),
        )

        with _auth_context("publisher-token"), pytest.raises(McpError) as exc_info:
            await _call_tool(mcp, "_store_result", **_store_args())

        assert exc_info.value.error.data == {"hub_code": "hub.result_type_not_allowed"}

    async def test_get_result_accepts_valid_consumer_token(self) -> None:
        config = _make_config()
        registry = _make_registry(
            services=[
                ServiceConfig(
                    name="publisher",
                    url="http://publisher/mcp",
                    hub_callback_token="publisher-token",
                ),
                ServiceConfig(
                    name="consumer",
                    url="http://consumer/mcp",
                    hub_callback_token="consumer-token",
                ),
            ],
            capabilities={
                "publisher": ServiceHubCapabilities(
                    supports_results_hub=True,
                    can_publish_results=True,
                    result_types=("ohlcv_bars",),
                ),
                "consumer": ServiceHubCapabilities(
                    supports_results_hub=True,
                    can_consume_results=True,
                    result_types=("ohlcv_bars",),
                ),
            },
        )
        store = ResultStore(config)
        mcp = create_mcp_server(
            config,
            registry,
            _make_agent(),
            SessionStore(),
            _AuthMap(
                {
                    "publisher-token": (AGENT_HUB_STORE,),
                    "consumer-token": (AGENT_HUB_FETCH,),
                }
            ),
            store,
        )

        with _auth_context("publisher-token"):
            stored = await _call_tool(mcp, "_store_result", **_store_args())

        with _auth_context("consumer-token"):
            result = await _call_tool(
                mcp,
                "_get_result",
                protocol_version=1,
                result_guid=stored["descriptor"]["result_guid"],
                hub_service="gofr-agent",
                expected_result_type="ohlcv_bars",
                expected_schema_id="gofr.ohlcv_bars.v1",
            )

        assert result["payload"] == [{"date": "2026-05-16", "close": 100.0}]
        assert result["metadata"]["producer_service"] == "publisher"

    async def test_get_result_rejects_unknown_guid(self) -> None:
        config = _make_config()
        registry = _make_registry(
            services=[
                ServiceConfig(
                    name="consumer",
                    url="http://consumer/mcp",
                    hub_callback_token="consumer-token",
                )
            ],
            capabilities={
                "consumer": ServiceHubCapabilities(
                    supports_results_hub=True,
                    can_consume_results=True,
                    result_types=("ohlcv_bars",),
                )
            },
        )
        mcp = create_mcp_server(
            config,
            registry,
            _make_agent(),
            SessionStore(),
            _AuthMap({"consumer-token": (AGENT_HUB_FETCH,)}),
            ResultStore(config),
        )

        with _auth_context("consumer-token"), pytest.raises(McpError) as exc_info:
            await _call_tool(
                mcp,
                "_get_result",
                protocol_version=1,
                result_guid="missing",
                hub_service="gofr-agent",
                expected_result_type="ohlcv_bars",
                expected_schema_id="gofr.ohlcv_bars.v1",
            )

        assert exc_info.value.error.data == {"hub_code": "hub.unknown_result"}

    async def test_get_result_rejects_expired_guid(self) -> None:
        clock = _FakeClock(datetime(2026, 5, 16, tzinfo=UTC))
        config = _make_config(hub_default_ttl_seconds=5)
        registry = _make_registry(
            services=[
                ServiceConfig(
                    name="publisher",
                    url="http://publisher/mcp",
                    hub_callback_token="publisher-token",
                ),
                ServiceConfig(
                    name="consumer",
                    url="http://consumer/mcp",
                    hub_callback_token="consumer-token",
                ),
            ],
            capabilities={
                "publisher": ServiceHubCapabilities(
                    supports_results_hub=True,
                    can_publish_results=True,
                    result_types=("ohlcv_bars",),
                ),
                "consumer": ServiceHubCapabilities(
                    supports_results_hub=True,
                    can_consume_results=True,
                    result_types=("ohlcv_bars",),
                ),
            },
        )
        store = ResultStore(config, clock=clock)
        mcp = create_mcp_server(
            config,
            registry,
            _make_agent(),
            SessionStore(),
            _AuthMap(
                {
                    "publisher-token": (AGENT_HUB_STORE,),
                    "consumer-token": (AGENT_HUB_FETCH,),
                }
            ),
            store,
        )

        with _auth_context("publisher-token"):
            stored = await _call_tool(mcp, "_store_result", **_store_args(ttl_seconds=5))

        clock.advance(6)

        with _auth_context("consumer-token"), pytest.raises(McpError) as exc_info:
            await _call_tool(
                mcp,
                "_get_result",
                protocol_version=1,
                result_guid=stored["descriptor"]["result_guid"],
                hub_service="gofr-agent",
                expected_result_type="ohlcv_bars",
                expected_schema_id="gofr.ohlcv_bars.v1",
            )

        assert exc_info.value.error.data == {"hub_code": "hub.expired_result"}

    async def test_get_result_rejects_schema_mismatch(self) -> None:
        config = _make_config()
        registry = _make_registry(
            services=[
                ServiceConfig(
                    name="publisher",
                    url="http://publisher/mcp",
                    hub_callback_token="publisher-token",
                ),
                ServiceConfig(
                    name="consumer",
                    url="http://consumer/mcp",
                    hub_callback_token="consumer-token",
                ),
            ],
            capabilities={
                "publisher": ServiceHubCapabilities(
                    supports_results_hub=True,
                    can_publish_results=True,
                    result_types=("ohlcv_bars",),
                ),
                "consumer": ServiceHubCapabilities(
                    supports_results_hub=True,
                    can_consume_results=True,
                    result_types=("ohlcv_bars",),
                ),
            },
        )
        store = ResultStore(config)
        mcp = create_mcp_server(
            config,
            registry,
            _make_agent(),
            SessionStore(),
            _AuthMap(
                {
                    "publisher-token": (AGENT_HUB_STORE,),
                    "consumer-token": (AGENT_HUB_FETCH,),
                }
            ),
            store,
        )

        with _auth_context("publisher-token"):
            stored = await _call_tool(mcp, "_store_result", **_store_args())

        with _auth_context("consumer-token"), pytest.raises(McpError) as exc_info:
            await _call_tool(
                mcp,
                "_get_result",
                protocol_version=1,
                result_guid=stored["descriptor"]["result_guid"],
                hub_service="gofr-agent",
                expected_result_type="ohlcv_bars",
                expected_schema_id="wrong.schema.v1",
            )

        assert exc_info.value.error.data == {"hub_code": "hub.schema_mismatch"}

    async def test_get_result_rejects_consumer_without_allowed_result_type(self) -> None:
        config = _make_config()
        registry = _make_registry(
            services=[
                ServiceConfig(
                    name="publisher",
                    url="http://publisher/mcp",
                    hub_callback_token="publisher-token",
                ),
                ServiceConfig(
                    name="consumer",
                    url="http://consumer/mcp",
                    hub_callback_token="consumer-token",
                ),
            ],
            capabilities={
                "publisher": ServiceHubCapabilities(
                    supports_results_hub=True,
                    can_publish_results=True,
                    result_types=("ohlcv_bars",),
                ),
                "consumer": ServiceHubCapabilities(
                    supports_results_hub=True,
                    can_consume_results=True,
                    result_types=("positions",),
                ),
            },
        )
        store = ResultStore(config)
        mcp = create_mcp_server(
            config,
            registry,
            _make_agent(),
            SessionStore(),
            _AuthMap(
                {
                    "publisher-token": (AGENT_HUB_STORE,),
                    "consumer-token": (AGENT_HUB_FETCH,),
                }
            ),
            store,
        )

        with _auth_context("publisher-token"):
            stored = await _call_tool(mcp, "_store_result", **_store_args())

        with _auth_context("consumer-token"), pytest.raises(McpError) as exc_info:
            await _call_tool(
                mcp,
                "_get_result",
                protocol_version=1,
                result_guid=stored["descriptor"]["result_guid"],
                hub_service="gofr-agent",
                expected_result_type="ohlcv_bars",
                expected_schema_id="gofr.ohlcv_bars.v1",
            )

        assert exc_info.value.error.data == {
            "hub_code": "hub.result_type_not_allowed"
        }

    async def test_describe_result_returns_metadata_only(self) -> None:
        config = _make_config()
        registry = _make_registry(
            services=[
                ServiceConfig(
                    name="publisher",
                    url="http://publisher/mcp",
                    hub_callback_token="publisher-token",
                ),
                ServiceConfig(
                    name="consumer",
                    url="http://consumer/mcp",
                    hub_callback_token="consumer-token",
                ),
            ],
            capabilities={
                "publisher": ServiceHubCapabilities(
                    supports_results_hub=True,
                    can_publish_results=True,
                    result_types=("ohlcv_bars",),
                ),
                "consumer": ServiceHubCapabilities(
                    supports_results_hub=True,
                    can_consume_results=True,
                    result_types=("ohlcv_bars",),
                ),
            },
        )
        store = ResultStore(config)
        mcp = create_mcp_server(
            config,
            registry,
            _make_agent(),
            SessionStore(),
            _AuthMap(
                {
                    "publisher-token": (AGENT_HUB_STORE,),
                    "consumer-token": (AGENT_HUB_FETCH,),
                }
            ),
            store,
        )

        with _auth_context("publisher-token"):
            stored = await _call_tool(mcp, "_store_result", **_store_args())

        with _auth_context("consumer-token"):
            result = await _call_tool(
                mcp,
                "_describe_result",
                protocol_version=1,
                result_guid=stored["descriptor"]["result_guid"],
                hub_service="gofr-agent",
                expected_result_type="ohlcv_bars",
                expected_schema_id="gofr.ohlcv_bars.v1",
            )

        assert "payload" not in result
        assert result["metadata"]["result_guid"] == stored["descriptor"]["result_guid"]


class TestListServicesHubRedaction:
    async def test_list_services_hides_reserved_tools_and_callback_tokens(self) -> None:
        config = _make_config()
        registry = _make_registry(
            services=[
                ServiceConfig(
                    name="fixture",
                    url="http://fixture/mcp",
                    hub_callback_token="fixture-callback-token",
                    description="Fixture service",
                )
            ],
            capabilities={},
            tools=[
                MCPToolInfo(
                    name="_register_results_hub",
                    description="Reserved hub registration",
                    input_schema={},
                    service_name="fixture",
                ),
                MCPToolInfo(
                    name="_debug_status",
                    description="Debug status",
                    input_schema={},
                    service_name="fixture",
                ),
                MCPToolInfo(
                    name="fetch_prices",
                    description="Fetch prices",
                    input_schema={},
                    service_name="fixture",
                ),
            ],
        )
        mcp = create_mcp_server(
            config,
            registry,
            _make_agent(),
            SessionStore(),
            _AuthMap({"admin-token": ("GoFRAgentListServices",)}),
            ResultStore(config),
        )

        with _auth_context("admin-token"):
            result = await _call_tool(mcp, "list_services")

        assert result[0]["name"] == "fixture"
        assert "hub_callback_token" not in result[0]
        assert "fixture-callback-token" not in str(result)
        tool_names = [tool["name"] for tool in result[0]["tools"]]
        assert "fixture___register_results_hub" not in tool_names
        assert "fixture___debug_status" in tool_names
        assert "fixture__fetch_prices" in tool_names
