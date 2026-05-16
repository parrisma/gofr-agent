"""Integration tests for GofrAgent with a live mock MCP backend.

Uses ``pydantic_ai.models.test.TestModel`` (via llm_model="test") so no real
LLM is contacted.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from app.agent.agent import GofrAgent
from app.agent.events import EventCollector, EventSink
from app.auth import ALL_ACTIVITIES
from app.config import GofrAgentConfig
from app.services import ServiceConfig, ServicesManifest
from app.services.registry import ServiceRegistry
from app.sessions.store import SessionStore
from tests.integration.test_analytics_hub_integration import (
    _start_stack as _start_descriptor_stack,
)

_TOKEN = "allow-all"


class _AllowAll:
    """Auth service that grants every activity to every token."""

    def authorised_activities(self, token: str) -> str:  # noqa: ARG002
        return ",".join(ALL_ACTIVITIES + ["MCPServer*"])


def _config() -> GofrAgentConfig:
    return GofrAgentConfig(llm_model="test")


def _manifest(url: str) -> ServicesManifest:
    svc = ServiceConfig(name="mock", url=url, description="Mock test service")
    return ServicesManifest(services=[svc])


@pytest.fixture()
async def registry(mock_mcp_url: str) -> ServiceRegistry:
    reg = ServiceRegistry(_config())
    await reg.load_manifest(_manifest(mock_mcp_url))
    yield reg  # type: ignore[misc]
    await reg.shutdown()


@pytest.fixture()
def session_store() -> SessionStore:
    return SessionStore(ttl_minutes=60)


class TestAgentIntegration:
    async def test_agent_answers_with_test_model(
        self, registry: ServiceRegistry, session_store: SessionStore
    ) -> None:
        """TestModel returns a canned answer — verifies pipeline end-to-end."""
        config = _config()
        agent = GofrAgent(config, registry, _AllowAll())
        agent.build()

        session = await session_store.get_or_create("s1")
        result = await agent.run("Hello", session, token=_TOKEN)

        assert isinstance(result.answer, str)
        assert len(result.answer) > 0

    async def test_session_history_accumulates(
        self, registry: ServiceRegistry, session_store: SessionStore
    ) -> None:
        """Messages are stored after each call."""
        config = _config()
        agent = GofrAgent(config, registry, _AllowAll())
        agent.build()

        session = await session_store.get_or_create("s2")
        await agent.run("First question", session, token=_TOKEN)
        msg_count_after_first = len(session.messages)

        await agent.run("Second question", session, token=_TOKEN)
        msg_count_after_second = len(session.messages)

        assert msg_count_after_second > msg_count_after_first

    async def test_concurrent_sessions_isolated(
        self, registry: ServiceRegistry, session_store: SessionStore
    ) -> None:
        """Two concurrent sessions should not interfere with each other."""
        config = _config()
        agent = GofrAgent(config, registry, _AllowAll())
        agent.build()

        s1 = await session_store.get_or_create("concurrent-1")
        s2 = await session_store.get_or_create("concurrent-2")

        await asyncio.gather(
            agent.run("Question A", s1, token=_TOKEN),
            agent.run("Question B", s2, token=_TOKEN),
        )

        # Sessions remain independent
        assert s1.messages is not s2.messages
        assert len(s1.messages) > 0
        assert len(s2.messages) > 0


def _tool_payload(messages: list[ModelMessage], tool_name: str) -> dict[str, Any] | None:
    for message in reversed(messages):
        if not isinstance(message, ModelRequest):
            continue
        for part in message.parts:
            if not isinstance(part, ToolReturnPart):
                continue
            if part.tool_name != tool_name or part.outcome != "success":
                continue
            payload = GofrAgent._parse_tool_payload(part.model_response_str())
            if payload is not None:
                return payload
    return None


def _has_long_list(value: Any, max_items: int) -> bool:
    if isinstance(value, list):
        if len(value) > max_items:
            return True
        return any(_has_long_list(item, max_items) for item in value)
    if isinstance(value, dict):
        return any(_has_long_list(item, max_items) for item in value.values())
    return False


def _descriptor_workflow_model(
    messages: list[ModelMessage],
    _agent_info: AgentInfo,
) -> ModelResponse:
    instrument_payload = _tool_payload(messages, "instruments__get_ohlcv_history")
    simple_return_payload = _tool_payload(messages, "analytics__simple_return")
    volatility_payload = _tool_payload(messages, "analytics__historical_volatility")
    drawdown_payload = _tool_payload(messages, "analytics__max_drawdown")

    if instrument_payload is None:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "instruments__get_ohlcv_history",
                    {
                        "ticker": "AAPL",
                        "from_date": "2026-04-01",
                        "to_date": "2026-05-13",
                    },
                )
            ]
        )

    if (
        simple_return_payload is None
        or volatility_payload is None
        or drawdown_payload is None
    ):
        descriptor = json.loads(instrument_payload["content"])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "analytics__simple_return",
                    {"ticker": "AAPL", "bars_ref": descriptor},
                ),
                ToolCallPart(
                    "analytics__historical_volatility",
                    {"ticker": "AAPL", "bars_ref": descriptor, "window": 30},
                ),
                ToolCallPart(
                    "analytics__max_drawdown",
                    {"ticker": "AAPL", "bars_ref": descriptor},
                ),
            ]
        )

    simple_return = json.loads(simple_return_payload["content"])
    volatility = json.loads(volatility_payload["content"])
    drawdown = json.loads(drawdown_payload["content"])
    answer = {
        "ticker": simple_return["ticker"],
        "from_date": simple_return["from_date"],
        "to_date": simple_return["to_date"],
        "simple_return": simple_return["return_pct"],
        "annualised_vol": volatility["annualised_vol"],
        "max_drawdown_pct": drawdown["max_drawdown_pct"],
    }
    return ModelResponse(
        parts=[TextPart(json.dumps(answer, sort_keys=True, separators=(",", ":")))]
    )


async def _descriptor_workflow_stream(
    messages: list[ModelMessage],
    agent_info: AgentInfo,
):
    response = _descriptor_workflow_model(messages, agent_info)
    for index, part in enumerate(response.parts):
        if isinstance(part, ToolCallPart):
            yield {
                index: DeltaToolCall(
                    name=part.tool_name,
                    json_args=part.args_as_json_str(),
                    tool_call_id=part.tool_call_id,
                )
            }
            continue
        if isinstance(part, TextPart):
            yield part.content
            continue
        raise AssertionError(f"Unexpected response part: {type(part).__name__}")


@pytest.mark.asyncio
class TestAgentDescriptorWorkflow:
    async def test_aapl_descriptor_workflow_keeps_raw_bars_out_of_events(self) -> None:
        stack = await _start_descriptor_stack()

        try:
            model = FunctionModel(
                function=_descriptor_workflow_model,
                stream_function=_descriptor_workflow_stream,
                model_name="function:descriptor",
            )
            config = GofrAgentConfig(llm_model="test")
            agent = GofrAgent(config, stack.registry, _AllowAll(), model=model)
            agent.build()
            session_store = SessionStore(ttl_minutes=60)
            session = await session_store.get_or_create("descriptor-workflow")
            collector = EventCollector(
                request_id="req-descriptor",
                session_id=session.session_id,
                max_payload_chars=config.max_event_payload_chars,
                max_response_steps=config.max_response_steps,
            )

            result = await agent.run(
                (
                    "Using downstream tools only, calculate AAPL simple return, "
                    "30-day historical volatility, and max drawdown from "
                    "2026-04-01 to 2026-05-13."
                ),
                session,
                token="dev-admin-token",
                max_steps=6,
                event_sink=EventSink(collector),
            )

            answer = json.loads(result.answer)
            volatility_payload = _tool_payload(
                session.messages,
                "analytics__historical_volatility",
            )

            assert answer["ticker"] == "AAPL"
            assert answer["annualised_vol"] is not None
            assert "simple_return" in answer
            assert "max_drawdown_pct" in answer
            assert volatility_payload is not None
            assert json.loads(volatility_payload["content"])["window"] == 30

            for event in collector.events:
                assert _has_long_list(event, 32) is False
                serialised = json.dumps(event, sort_keys=True)
                assert all(
                    token not in serialised
                    for token in ['"open"', '"high"', '"low"', '"close"']
                )
        finally:
            await stack.shutdown()
