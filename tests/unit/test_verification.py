"""Tests for verification-gap and clarification helpers."""

from __future__ import annotations

from app.agent.verification import (
    attempts_from_steps,
    build_clarification_request,
    build_verification_gap,
    detect_missing_fields,
)


class TestVerificationHelpers:
    def test_build_verification_gap_defaults_options(self) -> None:
        gap = build_verification_gap(
            request_id="req-1",
            requested_fact="future AAPL close",
            reason="no_service_registered",
        )

        assert gap.request_id == "req-1"
        assert gap.reason == "no_service_registered"
        assert gap.options

    def test_build_clarification_request_names_missing_fields(self) -> None:
        clarification = build_clarification_request(
            request_id="req-1",
            question="Compute volatility",
            missing_fields=["ticker", "window"],
        )

        assert clarification.missing_fields == ["ticker", "window"]
        assert "ticker, window" in clarification.prompt

    def test_detect_missing_fields_for_under_specified_finance_request(self) -> None:
        missing = detect_missing_fields("Compute volatility")

        assert "ticker" in missing
        assert "date_range" in missing
        assert "window" in missing

    def test_detect_missing_fields_ignores_output_return_instruction(self) -> None:
        missing = detect_missing_fields(
            "What is the exchange code for AAPL? Return compact JSON only."
        )

        assert missing == []

    def test_detect_missing_fields_for_finance_return_request(self) -> None:
        missing = detect_missing_fields("Compute returns for AAPL")

        assert "date_range" in missing

    def test_attempts_from_steps_carries_args_and_outcome(self) -> None:
        attempts = attempts_from_steps(
            [
                {
                    "kind": "tool_call",
                    "service": "instruments",
                    "tool": "get_spot_price",
                    "arguments": {"ticker": "AAPL"},
                },
                {
                    "kind": "tool_result",
                    "service": "instruments",
                    "tool": "get_spot_price",
                    "ok": False,
                },
            ]
        )

        assert attempts[0].service == "instruments"
        assert attempts[0].args_summary == {"ticker": "AAPL"}
        assert attempts[0].outcome == "tool_error"
