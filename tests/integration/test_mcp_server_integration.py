"""Integration tests: gofr-agent MCP server called via real MCP client."""

from __future__ import annotations

import threading

import pytest
import uvicorn
from gofr_common.web import AuthHeaderMiddleware
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from app.agent.agent import GofrAgent
from app.auth import ALL_ACTIVITIES
from app.config import GofrAgentConfig
from app.mcp_server.mcp_server import create_mcp_server
from app.services import ServiceConfig, ServicesManifest
from app.services.registry import ServiceRegistry
from app.sessions.store import SessionStore
from tests.integration.mock_mcp_server import _free_port


class _AllowAll:
    """Auth service that grants every activity to every token."""

    def authorised_activities(self, token: str) -> str:  # noqa: ARG002
        return ",".join(ALL_ACTIVITIES + ["MCPServer*"])


def _config() -> GofrAgentConfig:
    return GofrAgentConfig(llm_model="test")


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
    agent = GofrAgent(config, registry, _AllowAll())
    agent.build()
    session_store = SessionStore(ttl_minutes=60)

    mcp = create_mcp_server(config, registry, agent, session_store, _AllowAll())
    app = AuthHeaderMiddleware(mcp.streamable_http_app())

    port = _free_port()
    host = "127.0.0.1"
    thread = _AgentServerThread(app, host, port)
    thread.start()
    thread.wait_ready()

    yield f"http://{host}:{port}/mcp"  # type: ignore[misc]

    thread.shutdown()
    thread.join(timeout=5)
    await registry.shutdown()


_HEADERS = {"Authorization": "Bearer allow-all"}


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
