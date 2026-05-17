"""Tests for prompt-hardening contract models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel, ValidationError

from app.agent.contracts import (
    AgentRunStatus,
    ClarificationRequest,
    FactualClaimRecord,
    HumanInputRequest,
    HumanInputResponse,
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

    def test_human_input_request_serialises_as_plain_json(self) -> None:
        created = datetime(2026, 5, 17, tzinfo=UTC)
        request = HumanInputRequest(
            prompt_id="prompt-1",
            run_id="run-1",
            session_id="sess-1",
            prompt="Please provide ticker and date range.",
            created_at=created,
            expires_at=created + timedelta(minutes=10),
            missing_fields=["ticker", "date_range"],
        )

        payload = request.model_dump(mode="json")

        assert payload["prompt_id"] == "prompt-1"
        assert payload["run_id"] == "run-1"
        assert payload["session_id"] == "sess-1"
        assert payload["prompt"] == "Please provide ticker and date range."
        assert payload["missing_fields"] == ["ticker", "date_range"]
        assert payload["created_at"] == "2026-05-17T00:00:00Z"
        assert payload["expires_at"] == "2026-05-17T00:10:00Z"

    def test_human_input_request_schema_and_choices_round_trip(self) -> None:
        created = datetime(2026, 5, 17, tzinfo=UTC)
        request = HumanInputRequest(
            prompt_id="prompt-1",
            run_id="run-1",
            session_id="sess-1",
            prompt="Pick a ticker.",
            input_schema={"type": "object", "required": ["ticker"]},
            choices=["AAPL", "MSFT"],
            created_at=created,
            expires_at=created + timedelta(minutes=10),
        )

        payload = request.model_dump(mode="json")

        assert payload["input_schema"] == {"type": "object", "required": ["ticker"]}
        assert payload["choices"] == ["AAPL", "MSFT"]

    def test_human_input_request_rejects_extra_fields(self) -> None:
        created = datetime(2026, 5, 17, tzinfo=UTC)
        with pytest.raises(ValidationError):
            HumanInputRequest(
                prompt_id="prompt-1",
                run_id="run-1",
                session_id="sess-1",
                prompt="Pick a ticker.",
                created_at=created,
                expires_at=created + timedelta(minutes=10),
                extra="nope",  # type: ignore[call-arg]
            )

    def test_human_input_response_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            HumanInputResponse(
                session_id="sess-1",
                prompt_id="prompt-1",
                value={"ticker": "AAPL"},
                extra="nope",  # type: ignore[call-arg]
            )

    def test_agent_run_status_literal_rejects_unknown_values(self) -> None:
        class _Payload(BaseModel):
            status: AgentRunStatus

        with pytest.raises(ValidationError):
            _Payload(status="paused")

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
