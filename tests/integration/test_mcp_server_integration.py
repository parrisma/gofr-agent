"""Integration tests: gofr-agent MCP server called via real MCP client."""

from __future__ import annotations

import threading

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from app.agent.agent import GofrAgent
from app.config import GofrAgentConfig
from app.main_mcp import create_agent_asgi_app
from app.mcp_server.mcp_server import create_mcp_server
from app.services import ServiceConfig, ServicesManifest
from app.services.registry import ServiceHubCapabilities, ServiceRegistry
from app.sessions.store import SessionStore
from tests.helpers.dummy_auth_service import DummyAuthService
from tests.integration.mock_mcp_server import _free_port


def _config() -> GofrAgentConfig:
    return GofrAgentConfig(
        llm_model="test",
        mcp_allowed_hosts=["127.0.0.1:*", "gofr-agent-dev:8090"],
        mcp_allowed_origins=["http://localhost:3000"],
        cors_allowed_origins=["http://localhost:3000"],
    )


def _manifest(url: str) -> ServicesManifest:
    svc = ServiceConfig(name="mock", url=url, description="Mock test service")
    return ServicesManifest(services=[svc])


class _AgentServerThread(threading.Thread):
    """Run gofr-agent MCP server in a daemon thread."""

    def __init__(self, app: object, host: str, port: int) -> None:
        super().__init__(daemon=True)
        self.config = uvicorn.Config(app, host=host, port=port, log_level="error")
        self.server = uvicorn.Server(self.config)
        self._ready = threading.Event()
        _orig = self.server.startup

        async def _startup_and_signal(sockets=None) -> None:  # type: ignore[return]
            await _orig(sockets=sockets)
            self._ready.set()

        self.server.startup = _startup_and_signal  # type: ignore[method-assign]

    def run(self) -> None:  # pragma: no cover
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.server.serve())

    def wait_ready(self, timeout: float = 10.0) -> None:
        if not self._ready.wait(timeout):
            raise TimeoutError("gofr-agent MCP server did not start in time")

    def shutdown(self) -> None:
        self.server.should_exit = True


@pytest.fixture()
async def agent_server(mock_mcp_url: str) -> str:
    """Start an in-process gofr-agent and return its MCP URL."""
    config = _config()
    registry = ServiceRegistry(config)
    await registry.load_manifest(_manifest(mock_mcp_url))
    auth_service = DummyAuthService()
    agent = GofrAgent(config, registry, auth_service)
    agent.build()
    session_store = SessionStore(ttl_minutes=60)

    mcp = create_mcp_server(config, registry, agent, session_store, auth_service)
    app = create_agent_asgi_app(mcp, config, registry, agent)

    port = _free_port()
    host = "127.0.0.1"
    thread = _AgentServerThread(app, host, port)
    thread.start()
    thread.wait_ready()

    yield f"http://{host}:{port}/mcp"  # type: ignore[misc]

    thread.shutdown()
    thread.join(timeout=5)
    await registry.shutdown()


@pytest.fixture()
async def agent_server_with_hub_capabilities(mock_mcp_url: str) -> str:
    """Start an in-process gofr-agent with explicit hub capability metadata."""
    config = _config()
    registry = ServiceRegistry(config)
    await registry.load_manifest(_manifest(mock_mcp_url))
    registry.record_hub_capabilities(
        "mock",
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
    app = create_agent_asgi_app(mcp, config, registry, agent)

    port = _free_port()
    host = "127.0.0.1"
    thread = _AgentServerThread(app, host, port)
    thread.start()
    thread.wait_ready()

    yield f"http://{host}:{port}/mcp"  # type: ignore[misc]

    thread.shutdown()
    thread.join(timeout=5)
    await registry.shutdown()


_HEADERS = {"Authorization": "Bearer dev-admin-token"}


def _initialize_payload() -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "gofr-console-smoke", "version": "0.0.1"},
        },
    }


def _console_initialize_headers() -> dict[str, str]:
    return {
        "Host": "gofr-agent-dev:8090",
        "Origin": "http://localhost:3000",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": "Bearer dev-admin-token",
    }


class TestMCPServerIntegration:
    async def test_ping_tool(self, agent_server: str) -> None:
        async with (
            streamablehttp_client(agent_server, headers=_HEADERS) as (read, write, _),
            ClientSession(read, write) as client,
        ):
            await client.initialize()
            result = await client.call_tool("ping", {})
        import json

        data = json.loads(result.content[0].text)  # type: ignore[union-attr]
        assert data["status"] == "ok"
        assert data["service"] == "gofr-agent"

    async def test_health_check_tool(self, agent_server: str) -> None:
        async with (
            streamablehttp_client(agent_server, headers=_HEADERS) as (read, write, _),
            ClientSession(read, write) as client,
        ):
            await client.initialize()
            result = await client.call_tool("health_check", {})
        import json

        data = json.loads(result.content[0].text)  # type: ignore[union-attr]
        assert data["status"] == "healthy"
        assert data["service"] == "gofr-agent"
        assert data["config"]["models"]["selected"] == "test"
        assert data["downstream_services"]["total"] == 1

    async def test_list_services_tool(self, agent_server: str) -> None:
        async with (
            streamablehttp_client(agent_server, headers=_HEADERS) as (read, write, _),
            ClientSession(read, write) as client,
        ):
            await client.initialize()
            result = await client.call_tool("list_services", {})
        import json

        raw = result.content[0].text  # type: ignore[union-attr]
        data = json.loads(raw)
        # list_services returns either a list directly or wrapped dict
        if isinstance(data, dict):
            services = data.get("services", data.get("result", [data]))
        else:
            services = data
        assert any(s.get("name") == "mock" for s in services)

    async def test_list_services_includes_hub_capabilities(
        self,
        agent_server_with_hub_capabilities: str,
    ) -> None:
        async with (
            streamablehttp_client(agent_server_with_hub_capabilities, headers=_HEADERS) as (
                read,
                write,
                _,
            ),
            ClientSession(read, write) as client,
        ):
            await client.initialize()
            result = await client.call_tool("list_services", {})
        import json

        raw = result.content[0].text  # type: ignore[union-attr]
        data = json.loads(raw)
        services = (
            data if isinstance(data, list) else data.get("services", data.get("result", [data]))
        )
        service = next(item for item in services if item.get("name") == "mock")

        assert service["supports_results_hub"] is True
        assert service["can_publish_results"] is True
        assert service["can_consume_results"] is False
        assert service["result_types"] == ["ohlcv_bars"]
        assert "token" not in service
        assert "hub_callback_token" not in service

    async def test_ask_tool_returns_answer(self, agent_server: str) -> None:
        async with (
            streamablehttp_client(agent_server, headers=_HEADERS) as (read, write, _),
            ClientSession(read, write) as client,
        ):
            await client.initialize()
            result = await client.call_tool("ask", {"question": "Hello"})
        import json

        data = json.loads(result.content[0].text)  # type: ignore[union-attr]
        assert "answer" in data
        assert "session_id" in data

    async def test_ask_emits_reasoning_notifications(self, agent_server: str) -> None:
        import json

        notifications: list[dict[str, object]] = []

        async def _capture_log(params) -> None:  # type: ignore[no-untyped-def]
            if isinstance(params.data, dict):
                notifications.append(params.data)

        async with (
            streamablehttp_client(agent_server, headers=_HEADERS) as (read, write, _),
            ClientSession(read, write, logging_callback=_capture_log) as client,
        ):
            await client.initialize()
            result = await client.call_tool("ask", {"question": "Hello"})

        data = json.loads(result.content[0].text)  # type: ignore[union-attr]
        assert notifications
        assert notifications[0]["kind"] == "run_started"
        assert notifications[-1]["kind"] == "run_completed"
        assert all(event["request_id"] == data["request_id"] for event in notifications)
        expected_steps = [event for event in notifications if event["kind"] != "text_delta"]
        assert data["steps"] == expected_steps

    async def test_http_ping_without_token(self, agent_server: str) -> None:
        async with httpx.AsyncClient() as client:
            response = await client.get(agent_server.removesuffix("/mcp") + "/ping")

        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "gofr-agent"

    async def test_http_health_without_token(self, agent_server: str) -> None:
        async with httpx.AsyncClient() as client:
            response = await client.get(agent_server.removesuffix("/mcp") + "/health")

        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "gofr-agent"
        assert data["downstream"] == {
            "total": 1,
            "healthy": 1,
            "degraded": 0,
            "failed": 0,
        }
        assert "config" not in data
        assert "items" not in data["downstream"]

    async def test_console_shaped_initialize_is_allowed(self, agent_server: str) -> None:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                agent_server,
                headers=_console_initialize_headers(),
                json=_initialize_payload(),
            )

        assert response.status_code == 200
        assert response.headers["mcp-session-id"]
        assert "event:" in response.text or "jsonrpc" in response.text

    async def test_disallowed_origin_is_rejected(self, agent_server: str) -> None:
        headers = _console_initialize_headers()
        headers["Origin"] = "http://evil.example"

        async with httpx.AsyncClient() as client:
            response = await client.post(agent_server, headers=headers, json=_initialize_payload())

        assert response.status_code == 403
        assert response.text == "Invalid Origin header"

    async def test_disallowed_host_is_rejected(self, agent_server: str) -> None:
        headers = _console_initialize_headers()
        headers["Host"] = "evil.example"

        async with httpx.AsyncClient() as client:
            response = await client.post(agent_server, headers=headers, json=_initialize_payload())

        assert response.status_code == 421
        assert response.text == "Invalid Host header"

    async def test_cors_preflight_allows_configured_console_origin(
        self,
        agent_server: str,
    ) -> None:
        async with httpx.AsyncClient() as client:
            response = await client.options(
                agent_server,
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": ", ".join(
                        ["Authorization", "Content-Type", "Accept", "Mcp-Session-Id"]
                    ),
                },
            )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
        assert "Mcp-Session-Id" in response.headers["access-control-allow-headers"]

    async def test_cors_preflight_rejects_unconfigured_origin(self, agent_server: str) -> None:
        async with httpx.AsyncClient() as client:
            response = await client.options(
                agent_server,
                headers={
                    "Origin": "http://evil.example",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "Authorization",
                },
            )

        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers

    async def test_mcp_tool_execution_fails_closed_with_invalid_token(
        self,
        agent_server: str,
    ) -> None:
        async with (
            streamablehttp_client(
                agent_server,
                headers={"Authorization": "Bearer invalid-token"},
            ) as (read, write, _),
            ClientSession(read, write) as client,
        ):
            await client.initialize()
            result = await client.call_tool("ping", {})

        assert result.isError

    async def test_reset_session_tool(self, agent_server: str) -> None:
        async with (
            streamablehttp_client(agent_server, headers=_HEADERS) as (read, write, _),
            ClientSession(read, write) as client,
        ):
            await client.initialize()
            # First create a session
            r1 = await client.call_tool("ask", {"question": "Hi", "session_id": "test-s"})
            import json

            d1 = json.loads(r1.content[0].text)  # type: ignore[union-attr]
            assert d1["session_id"] == "test-s"

            # Reset it
            r2 = await client.call_tool("reset_session", {"session_id": "test-s"})
            d2 = json.loads(r2.content[0].text)  # type: ignore[union-attr]
            assert d2["status"] == "ok"
