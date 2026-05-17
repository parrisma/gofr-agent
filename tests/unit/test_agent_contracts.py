"""Tests for prompt-hardening contract models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent.contracts import (
    ClarificationRequest,
    FactualClaimRecord,
    IntentConstraints,
    ProvenanceRecord,
    VerificationGap,
    VerificationGapAttempt,
)


class TestPromptHardeningContracts:
    def test_intent_constraints_defaults_are_json_serialisable(self) -> None:
        payload = IntentConstraints().model_dump(mode="json")

        assert payload == {
            "forbidden_services": [],
            "forbidden_tools": [],
            "allowed_services": [],
            "tools_only": False,
            "output_format": None,
            "no_commentary": False,
        }

    def test_verification_gap_matches_documented_shape(self) -> None:
        gap = VerificationGap(
            request_id="req-1",
            requested_fact="AAPL close",
            attempted=[
                VerificationGapAttempt(
                    service="instruments",
                    tool="get_spot_price",
                    args_summary={"ticker": "AAPL"},
                    outcome="empty_result",
                )
            ],
            reason="empty_result",
            options=["supply the fact"],
        )

        assert gap.model_dump(mode="json") == {
            "request_id": "req-1",
            "requested_fact": "AAPL close",
            "attempted": [
                {
                    "service": "instruments",
                    "tool": "get_spot_price",
                    "args_summary": {"ticker": "AAPL"},
                    "outcome": "empty_result",
                }
            ],
            "reason": "empty_result",
            "options": ["supply the fact"],
        }

    def test_gap_reason_is_enumerated(self) -> None:
        with pytest.raises(ValidationError):
            VerificationGap(
                request_id="req-1",
                requested_fact="fact",
                attempted=[],
                reason="maybe",  # type: ignore[arg-type]
                options=[],
            )

    def test_clarification_request_has_request_id_and_missing_fields(self) -> None:
        clarification = ClarificationRequest(
            request_id="req-1",
            question="Compute volatility",
            missing_fields=["ticker", "window"],
            reason="materially_under_specified",
            prompt="Please provide ticker and window.",
        )

        assert clarification.request_id == "req-1"
        assert clarification.missing_fields == ["ticker", "window"]

    def test_provenance_record_carries_args_hash_and_as_of(self) -> None:
        record = ProvenanceRecord(
            request_id="req-1",
            service="instruments",
            tool="get_spot_price",
            args_hash="abc123",
            artifact_id="tool_result_1",
            as_of="2026-05-13T00:00:00Z",
        )

        assert record.model_dump(mode="json")["as_of"] == "2026-05-13T00:00:00Z"

    def test_factual_claim_record_is_plain_json(self) -> None:
        claim = FactualClaimRecord(
            claim="AAPL spot price is 189.45",
            provenance=[
                ProvenanceRecord(
                    request_id="req-1",
                    service="instruments",
                    tool="get_spot_price",
                    args_hash="abc123",
                )
            ],
            verified=True,
        )

        assert claim.model_dump(mode="json")["provenance"][0]["service"] == "instruments"
