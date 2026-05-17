"""Tests for deterministic grounding checks."""

from __future__ import annotations

from app.agent.contracts import IntentConstraints
from app.agent.grounding import assess_grounding
from app.services import ServiceConfig
from app.services.discovery import MCPToolInfo


def _svc(name: str) -> ServiceConfig:
    return ServiceConfig(name=name, url=f"http://{name}/mcp")


def _tool(name: str, description: str = "returns numeric price") -> MCPToolInfo:
    return MCPToolInfo(
        name=name,
        description=description,
        input_schema={},
        service_name="instruments",
    )


class TestGrounding:
    def test_tools_only_without_calls_returns_gap(self) -> None:
        gap = assess_grounding(
            request_id="req-1",
            question="Explain Sharpe ratio",
            answer="Sharpe ratio compares return to volatility.",
            steps=[],
            services=[_svc("instruments")],
            tools=[_tool("get_price")],
            constraints=IntentConstraints(tools_only=True),
        )

        assert gap is not None
        assert gap.reason == "tool_error"

    def test_numeric_answer_without_numeric_tool_call_returns_gap(self) -> None:
        gap = assess_grounding(
            request_id="req-1",
            question="What is AAPL price?",
            answer="189.45",
            steps=[],
            services=[_svc("instruments")],
            tools=[_tool("get_spot_price")],
            constraints=IntentConstraints(),
        )

        assert gap is not None
        assert gap.reason == "tool_error"

    def test_failed_tool_then_numeric_answer_returns_gap_with_attempt(self) -> None:
        gap = assess_grounding(
            request_id="req-1",
            question="What is AAPL price?",
            answer="189.45",
            steps=[
                {
                    "kind": "tool_result",
                    "service": "instruments",
                    "tool": "get_spot_price",
                    "ok": False,
                }
            ],
            services=[_svc("instruments")],
            tools=[_tool("get_spot_price")],
            constraints=IntentConstraints(),
        )

        assert gap is not None
        assert gap.attempted[0].outcome == "tool_error"

    def test_tools_only_failed_constraint_result_returns_gap_without_digit(self) -> None:
        gap = assess_grounding(
            request_id="req-1",
            question="What is AAPL exchange?",
            answer="I cannot use the forbidden service.",
            steps=[
                {
                    "kind": "tool_result",
                    "service": "instruments",
                    "tool": "instrument_lookup",
                    "ok": False,
                    "summary": {"message": "service 'instruments' is forbidden"},
                }
            ],
            services=[_svc("instruments")],
            tools=[_tool("instrument_lookup")],
            constraints=IntentConstraints(tools_only=True),
        )

        assert gap is not None
        assert gap.reason == "constraint_blocked"

    def test_non_factual_answer_without_digits_passes(self) -> None:
        gap = assess_grounding(
            request_id="req-1",
            question="Explain alpha",
            answer="Alpha is excess return relative to a benchmark.",
            steps=[],
            services=[_svc("analytics")],
            tools=[_tool("simple_return")],
            constraints=IntentConstraints(),
        )

        assert gap is None
