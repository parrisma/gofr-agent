"""Tests for deterministic prompt-hardening graders."""

from __future__ import annotations

from tests.helpers.prompt_hardening_grader import (
    answer_excludes_injection,
    forbidden_tool_absent,
    has_clarification_fields,
    has_valid_verification_gap,
    parses_json_with_exact_keys,
    provenance_covers,
    tool_call_occurred,
)


def _payload() -> dict:
    return {
        "answer": '{"exchange":"XNAS"}',
        "steps": [{"kind": "tool_call", "service": "instruments", "tool": "lookup"}],
        "verification_gap": {
            "request_id": "req-1",
            "requested_fact": "future price",
            "attempted": [{"service": "instruments"}],
            "reason": "tool_error",
        },
        "clarification_request": {"missing_fields": ["ticker"]},
        "provenance": [
            {"service": "instruments", "tool": "lookup", "args_hash": "abc123"}
        ],
    }


class TestPromptHardeningGrader:
    def test_tool_predicates(self) -> None:
        payload = _payload()

        assert tool_call_occurred(payload, service="instruments", tool="lookup")
        assert forbidden_tool_absent(payload, service="trades")

    def test_json_exact_keys(self) -> None:
        assert parses_json_with_exact_keys('{"exchange":"XNAS"}', {"exchange"})

    def test_gap_clarification_and_provenance(self) -> None:
        payload = _payload()

        assert has_valid_verification_gap(payload, attempted_required=True)
        assert has_clarification_fields(payload)
        assert provenance_covers(payload, service="instruments", tool="lookup")

    def test_injection_marker_absent(self) -> None:
        assert answer_excludes_injection(_payload(), "FAKE999")
