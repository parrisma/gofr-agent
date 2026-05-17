"""Tests for intent constraints."""

from __future__ import annotations

from app.agent.intent import build_intent_constraints, check_tool_allowed


class TestIntentConstraints:
    def test_structured_fields_take_precedence(self) -> None:
        constraints = build_intent_constraints(
            instructions="Use only instruments. Do not use trades.",
            forbidden_services=["analytics"],
            allowed_services=["clients"],
        )

        assert constraints.forbidden_services == ["analytics", "trades"]
        assert constraints.allowed_services == ["clients", "instruments"]

    def test_regex_extraction_only_uses_instructions(self) -> None:
        constraints = build_intent_constraints()

        assert constraints.forbidden_services == []
        assert constraints.allowed_services == []

    def test_forbidden_service_blocks_tool(self) -> None:
        constraints = build_intent_constraints(forbidden_services=["trades"])

        allowed, reason = check_tool_allowed(
            constraints,
            service="trades",
            tool="list_trades",
        )

        assert allowed is False
        assert reason == "service 'trades' is forbidden"

    def test_allowed_services_block_everything_else(self) -> None:
        constraints = build_intent_constraints(allowed_services=["instruments"])

        allowed, reason = check_tool_allowed(
            constraints,
            service="analytics",
            tool="simple_return",
        )

        assert allowed is False
        assert reason == "service 'analytics' is outside allowed_services"

    def test_forbidden_tool_accepts_full_or_dotted_name(self) -> None:
        constraints = build_intent_constraints(forbidden_tools=["analytics.simple_return"])

        allowed, _reason = check_tool_allowed(
            constraints,
            service="analytics",
            tool="simple_return",
        )

        assert allowed is False
