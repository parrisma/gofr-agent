"""Live OpenRouter integration tests.

These tests make real HTTP calls to the OpenRouter API and therefore require:

    OPENROUTER_API_KEY=<your key>          — required
    OPENROUTER_MODEL=<model string>        — optional (default below)

Run selectively:

    uv run python -m pytest tests/integration/test_openrouter.py -v

All tests are marked ``openrouter`` and are skipped automatically when the env
var is absent so they never block CI.
"""

from __future__ import annotations

import json
import os
import threading

import pytest
import uvicorn
from gofr_common.web import AuthHeaderMiddleware
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.agent.agent import GofrAgent
from app.auth import ALL_ACTIVITIES
from app.config import GofrAgentConfig
from app.mcp_server.mcp_server import create_mcp_server
from app.services import ServiceConfig, ServicesManifest
from app.services.registry import ServiceRegistry
from app.sessions.store import SessionStore
from tests.integration.mock_mcp_server import _free_port

# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_DEFAULT_MODEL = "deepseek/deepseek-v4-pro"
_TOKEN = "test-openrouter-token"

pytestmark = pytest.mark.openrouter


def _api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        pytest.skip("OPENROUTER_API_KEY not set")
    return key


def _model_name() -> str:
    return os.environ.get("OPENROUTER_MODEL", _DEFAULT_MODEL)


def _openrouter_model() -> OpenAIChatModel:
    """Return a pydantic-ai model pointed at OpenRouter."""
    return OpenAIChatModel(
        _model_name(),
        provider=OpenAIProvider(
            base_url=_OPENROUTER_BASE,
            api_key=_api_key(),
        ),
    )


class _AllowAll:
    """Auth service that grants every activity to every token."""

    def authorised_activities(self, token: str) -> str:  # noqa: ARG002
        return ",".join(ALL_ACTIVITIES + ["MCPServer*"])


def _manifest(url: str) -> ServicesManifest:
    svc = ServiceConfig(name="mock", url=url, description="Mock test service")
    return ServicesManifest(services=[svc])


def _fixture_services_manifest(
    instruments_url: str,
    clients_url: str,
    trades_url: str,
    analytics_url: str,
) -> ServicesManifest:
    """Return a manifest containing all synthetic finance fixture services."""
    return ServicesManifest(
        services=[
            ServiceConfig(
                name="instruments",
                url=instruments_url,
                description="Instrument reference data, spot prices, and OHLCV history",
            ),
            ServiceConfig(
                name="clients",
                url=clients_url,
                description="Client master data, holdings, watchlists, and mandates",
            ),
            ServiceConfig(
                name="trades",
                url=trades_url,
                description="Trade blotter retrieval, aggregation, and realised P&L",
            ),
            ServiceConfig(
                name="analytics",
                url=analytics_url,
                description="Derived analytics for market data, positions, and executions",
            ),
        ]
    )


def _json_object_from_answer(answer: str) -> dict:
    """Parse a JSON object returned by the LLM, tolerating markdown fences."""
    text = answer.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start:end + 1]
    return json.loads(text)


def _services_from_result_text(text: str) -> list[dict]:
    """Parse list_services output across FastMCP result serialization shapes."""
    data = json.loads(text)
    services = data.get("services", data.get("result", [data])) if isinstance(data, dict) else data
    return services


def _services_from_result_content(content: list[object]) -> list[dict]:
    """Parse list_services output from one or many text content items."""
    services: list[dict] = []
    for item in content:
        services.extend(_services_from_result_text(item.text))  # type: ignore[attr-defined]
    return services


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
async def or_registry(mock_mcp_url: str) -> ServiceRegistry:
    """Registry pre-loaded with the mock MCP service."""
    config = GofrAgentConfig(llm_model="test")  # model overridden per-test
    reg = ServiceRegistry(config)
    await reg.load_manifest(_manifest(mock_mcp_url))
    yield reg  # type: ignore[misc]
    await reg.shutdown()


@pytest.fixture()
def session_store() -> SessionStore:
    return SessionStore(ttl_minutes=60)


class _AgentServerThread(threading.Thread):
    """Run gofr-agent MCP server in a daemon thread."""

    def __init__(self, app: object, host: str, port: int) -> None:
        super().__init__(daemon=True)
        cfg = uvicorn.Config(app, host=host, port=port, log_level="error")
        self.server = uvicorn.Server(cfg)
        self._ready = threading.Event()
        orig = self.server.startup

        async def _startup_and_signal(sockets=None) -> None:  # type: ignore[return]
            await orig(sockets=sockets)
            self._ready.set()

        self.server.startup = _startup_and_signal  # type: ignore[method-assign]

    def run(self) -> None:  # pragma: no cover
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.server.serve())

    def wait_ready(self, timeout: float = 30.0) -> None:
        if not self._ready.wait(timeout):
            raise TimeoutError("Agent MCP server did not start in time")

    def shutdown(self) -> None:
        self.server.should_exit = True


@pytest.fixture()
async def or_agent_server(mock_mcp_url: str) -> str:  # type: ignore[misc]
    """Start gofr-agent backed by a real OpenRouter model; yield its MCP URL."""
    model = _openrouter_model()
    config = GofrAgentConfig()
    auth_service = _AllowAll()
    registry = ServiceRegistry(config)
    await registry.load_manifest(_manifest(mock_mcp_url))
    agent = GofrAgent(config, registry, auth_service, model=model)
    agent.build()
    store = SessionStore(ttl_minutes=60)
    mcp = create_mcp_server(config, registry, agent, store, auth_service)
    app = AuthHeaderMiddleware(mcp.streamable_http_app())

    port = _free_port()
    host = "127.0.0.1"
    thread = _AgentServerThread(app, host, port)
    thread.start()
    thread.wait_ready()

    yield f"http://{host}:{port}/mcp"

    thread.shutdown()
    thread.join(timeout=10)
    await registry.shutdown()


@pytest.fixture()
async def or_agent_server_with_fixture_services(
    instruments_url: str,
    clients_url: str,
    trades_url: str,
    analytics_url: str,
) -> str:  # type: ignore[misc]
    """Start gofr-agent backed by OpenRouter and all finance fixture services."""
    model = _openrouter_model()
    config = GofrAgentConfig()
    auth_service = _AllowAll()
    registry = ServiceRegistry(config)
    await registry.load_manifest(
        _fixture_services_manifest(
            instruments_url,
            clients_url,
            trades_url,
            analytics_url,
        )
    )
    agent = GofrAgent(config, registry, auth_service, model=model)
    agent.build()
    store = SessionStore(ttl_minutes=60)
    mcp = create_mcp_server(config, registry, agent, store, auth_service)
    app = AuthHeaderMiddleware(mcp.streamable_http_app())

    port = _free_port()
    host = "127.0.0.1"
    thread = _AgentServerThread(app, host, port)
    thread.start()
    thread.wait_ready()

    yield f"http://{host}:{port}/mcp"

    thread.shutdown()
    thread.join(timeout=10)
    await registry.shutdown()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOpenRouterDirect:
    """Agent called directly (no HTTP layer) with a real LLM."""

    async def test_simple_question_returns_non_empty_answer(
        self, or_registry: ServiceRegistry, session_store: SessionStore
    ) -> None:
        """A plain factual question gets a non-empty string answer."""
        agent = GofrAgent(
            GofrAgentConfig(), or_registry, _AllowAll(), model=_openrouter_model()
        )
        agent.build()

        session = await session_store.get_or_create("or-direct-1")
        result = await agent.run(
            "Reply with the single word: pong",
            session,
            token=_TOKEN,
        )

        assert isinstance(result.answer, str)
        assert len(result.answer.strip()) > 0
        assert result.tokens_used > 0

    async def test_conversation_history_is_used(
        self, or_registry: ServiceRegistry, session_store: SessionStore
    ) -> None:
        """A second question in the same session can refer back to the first answer."""
        agent = GofrAgent(
            GofrAgentConfig(), or_registry, _AllowAll(), model=_openrouter_model()
        )
        agent.build()

        session = await session_store.get_or_create("or-direct-2")
        r1 = await agent.run(
            "I am thinking of the number 42. Remember it.",
            session,
            token=_TOKEN,
        )
        assert r1.answer  # first turn acknowledged

        r2 = await agent.run(
            "What number am I thinking of?",
            session,
            token=_TOKEN,
        )
        # The model should recall 42 from history
        assert "42" in r2.answer

    async def test_tool_call_echo(
        self, or_registry: ServiceRegistry, session_store: SessionStore
    ) -> None:
        """The model can invoke the mock MCP 'echo' tool and return its output."""
        agent = GofrAgent(
            GofrAgentConfig(), or_registry, _AllowAll(), model=_openrouter_model()
        )
        agent.build()

        session = await session_store.get_or_create("or-direct-3")
        result = await agent.run(
            "Use the mock__echo tool with message='hello-from-test' "
            "and return exactly what it gives back.",
            session,
            token=_TOKEN,
        )

        assert "hello-from-test" in result.answer

    async def test_tool_call_add(
        self, or_registry: ServiceRegistry, session_store: SessionStore
    ) -> None:
        """The model can call the mock MCP 'add' tool and report the result."""
        agent = GofrAgent(
            GofrAgentConfig(), or_registry, _AllowAll(), model=_openrouter_model()
        )
        agent.build()

        session = await session_store.get_or_create("or-direct-4")
        result = await agent.run(
            "Call mock__add with a=17 and b=25. After the tool returns, "
            "reply with only the numeric result and no other text.",
            session,
            token=_TOKEN,
        )

        assert "42" in result.answer


class TestOpenRouterViaMCP:
    """Full end-to-end: real model called through the live gofr-agent MCP server."""

    async def test_ping(self, or_agent_server: str) -> None:
        """Ping works without touching the LLM."""
        async with (
            streamablehttp_client(
                or_agent_server,
                headers={"Authorization": f"Bearer {_TOKEN}"},
            ) as (r, w, _),
            ClientSession(r, w) as client,
        ):
            await client.initialize()
            result = await client.call_tool("ping", {})

        data = json.loads(result.content[0].text)  # type: ignore[union-attr]
        assert data["status"] == "ok"

    async def test_ask_returns_answer(self, or_agent_server: str) -> None:
        """The 'ask' MCP tool makes a real LLM call and returns a non-empty answer."""
        async with (
            streamablehttp_client(
                or_agent_server,
                headers={"Authorization": f"Bearer {_TOKEN}"},
            ) as (r, w, _),
            ClientSession(r, w) as client,
        ):
            await client.initialize()
            result = await client.call_tool(
                "ask", {"question": "Reply with the single word: pong"}
            )

        data = json.loads(result.content[0].text)  # type: ignore[union-attr]
        assert "answer" in data
        assert len(data["answer"].strip()) > 0
        assert "session_id" in data

    async def test_ask_with_tool_use(self, or_agent_server: str) -> None:
        """LLM correctly uses a downstream tool when asked via MCP."""
        async with (
            streamablehttp_client(
                or_agent_server,
                headers={"Authorization": f"Bearer {_TOKEN}"},
            ) as (r, w, _),
            ClientSession(r, w) as client,
        ):
            await client.initialize()
            result = await client.call_tool(
                "ask",
                {
                    "question": (
                        "Use the mock__add tool to add 100 and 200 "
                        "and tell me the result."
                    )
                },
            )

        data = json.loads(result.content[0].text)  # type: ignore[union-attr]
        assert "300" in data["answer"]

    async def test_session_continuity(self, or_agent_server: str) -> None:
        """Two 'ask' calls sharing a session_id maintain conversational context."""
        sid = "or-mcp-session-continuity"
        headers = {"Authorization": f"Bearer {_TOKEN}"}

        async with (
            streamablehttp_client(or_agent_server, headers=headers) as (r, w, _),
            ClientSession(r, w) as client,
        ):
            await client.initialize()
            await client.call_tool(
                "ask",
                {
                    "question": "I am thinking of the number 99. Remember it.",
                    "session_id": sid,
                },
            )
            r2 = await client.call_tool(
                "ask",
                {"question": "What number am I thinking of?", "session_id": sid},
            )

        data = json.loads(r2.content[0].text)  # type: ignore[union-attr]
        assert "99" in data["answer"]

    async def test_ask_reasons_across_all_fixture_services(
        self, or_agent_server_with_fixture_services: str
    ) -> None:
        """Agent can combine client, instrument, trade, and analytics services."""
        headers = {"Authorization": f"Bearer {_TOKEN}"}

        async with (
            streamablehttp_client(
                or_agent_server_with_fixture_services,
                headers=headers,
            ) as (r, w, _),
            ClientSession(r, w) as client,
        ):
            await client.initialize()

            services_result = await client.call_tool("list_services", {})
            services = _services_from_result_content(services_result.content)
            assert {svc["name"] for svc in services} == {
                "instruments",
                "clients",
                "trades",
                "analytics",
            }

            ask_result = await client.call_tool(
                "ask",
                {
                    "session_id": "or-mcp-all-fixtures",
                    "max_steps": 12,
                    "question": (
                        "Use the downstream tools, not prior knowledge, to answer this. "
                        "Look up Meridian Capital, get its AAPL holding, resolve AAPL, "
                        "get the current AAPL spot price, compute the position market value "
                        "with analytics, and get realised P&L for Meridian Capital's AAPL "
                        "trades. Return only compact JSON with these keys: client_id, ticker, "
                        "instrument_name, quantity, spot_price, currency, market_value, "
                        "realised_pnl, matched_trades, conclusion."
                    ),
                },
            )

        data = json.loads(ask_result.content[0].text)  # type: ignore[union-attr]
        answer = _json_object_from_answer(data["answer"])

        assert answer["client_id"] == "C001"
        assert answer["ticker"] == "AAPL"
        assert "Apple" in answer["instrument_name"]
        assert answer["quantity"] == 5000
        assert answer["spot_price"] == pytest.approx(189.45)
        assert answer["currency"] == "USD"
        assert answer["market_value"] == pytest.approx(947250.0)
        assert answer["realised_pnl"] == pytest.approx(4600.0)
        assert answer["matched_trades"] == 1
