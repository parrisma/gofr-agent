"""Tests for typed reasoning events and collection helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.agent.events import (
    EventCollector,
    RunCompletedEvent,
    RunPausedEvent,
    RunResumedEvent,
    RunStartedEvent,
    TextDeltaCoalescer,
    TextDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
    UserInputReceivedEvent,
    UserInputRequestedEvent,
)


def _timestamp(seconds: float) -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)


class TestReasoningEvents:
    def test_event_serialises_to_plain_json_compatible_dict(self) -> None:
        event = ToolCallEvent(
            request_id="req-1",
            session_id="sess-1",
            service="analytics",
            tool="lookup",
            arguments={"symbol": "AAPL"},
        )

        payload = event.model_dump(mode="json")

        assert payload["kind"] == "tool_call"
        assert payload["service"] == "analytics"
        assert payload["tool"] == "lookup"
        assert payload["arguments"] == {"symbol": "AAPL"}
        assert isinstance(payload["timestamp"], str)

    def test_sequence_numbers_are_monotonic(self) -> None:
        collector = EventCollector("req-1", "sess-1")

        first = collector.record(RunStartedEvent(request_id="x", session_id="y"))
        second = collector.record(
            RunCompletedEvent(request_id="x", session_id="y", model="test:model")
        )

        assert first["sequence"] == 1
        assert second["sequence"] == 2

    def test_collector_applies_run_id_to_events(self) -> None:
        collector = EventCollector("req-1", "sess-1", run_id="run-1")

        event = collector.record(RunStartedEvent(request_id="x", session_id="y"))

        assert event["run_id"] == "run-1"

    def test_user_input_requested_event_serialises(self) -> None:
        event = UserInputRequestedEvent(
            request_id="req-1",
            session_id="sess-1",
            run_id="run-1",
            prompt_id="prompt-1",
            prompt="Please provide ticker.",
            missing_fields=["ticker"],
        )

        payload = event.model_dump(mode="json")

        assert payload["kind"] == "user_input_requested"
        assert payload["run_id"] == "run-1"
        assert payload["prompt_id"] == "prompt-1"
        assert payload["prompt"] == "Please provide ticker."
        assert payload["missing_fields"] == ["ticker"]
        assert isinstance(payload["timestamp"], str)

    def test_user_input_received_event_does_not_carry_value(self) -> None:
        payload = UserInputReceivedEvent(
            request_id="req-1",
            session_id="sess-1",
            run_id="run-1",
            prompt_id="prompt-1",
        ).model_dump(mode="json")

        assert payload["kind"] == "user_input_received"
        assert "value" not in payload

    def test_user_input_events_are_in_final_steps(self) -> None:
        collector = EventCollector("req-1", "sess-1")
        collector.record(
            UserInputRequestedEvent(
                request_id="x",
                session_id="y",
                run_id="run-1",
                prompt_id="prompt-1",
                prompt="Need ticker.",
            )
        )
        collector.record(
            RunPausedEvent(
                request_id="x",
                session_id="y",
                run_id="run-1",
                prompt_id="prompt-1",
            )
        )
        collector.record(
            UserInputReceivedEvent(
                request_id="x",
                session_id="y",
                run_id="run-1",
                prompt_id="prompt-1",
            )
        )
        collector.record(
            RunResumedEvent(
                request_id="x",
                session_id="y",
                run_id="run-1",
                prompt_id="prompt-1",
            )
        )

        steps = collector.build_steps()

        assert [step["kind"] for step in steps] == [
            "user_input_requested",
            "run_paused",
            "user_input_received",
            "run_resumed",
        ]
        assert [step["sequence"] for step in steps] == [1, 2, 3, 4]

    def test_final_steps_are_derived_from_collected_events(self) -> None:
        collector = EventCollector("req-1", "sess-1")
        collector.record(RunStartedEvent(request_id="x", session_id="y"))
        collector.record(TextDeltaEvent(request_id="x", session_id="y", text="hello"))
        collector.record(
            ToolCallEvent(
                request_id="x",
                session_id="y",
                service="svc",
                tool="lookup",
            )
        )
        collector.record(
            ToolResultEvent(
                request_id="x",
                session_id="y",
                service="svc",
                tool="lookup",
                ok=True,
                summary="done",
            )
        )
        collector.record(
            RunCompletedEvent(
                request_id="x",
                session_id="y",
                model="test:model",
                answer_preview="done",
            )
        )

        steps = collector.build_steps()

        assert [step["kind"] for step in steps] == [
            "run_started",
            "tool_call",
            "tool_result",
            "run_completed",
        ]

    def test_payloads_truncate_and_mark_truncated(self) -> None:
        collector = EventCollector("req-1", "sess-1", max_payload_chars=5)

        event = collector.record(
            ToolResultEvent(
                request_id="x",
                session_id="y",
                service="svc",
                tool="lookup",
                ok=True,
                summary={"text": "abcdefghij"},
            )
        )

        assert event["truncated"] is True
        assert event["summary"]["text"] == "abcde...[truncated]"

    def test_truncation_preserves_provenance_fields(self) -> None:
        collector = EventCollector("req-1", "sess-1", max_payload_chars=4)

        recorded = collector.record(
            ToolResultEvent(
                request_id="req-1",
                session_id="sess-1",
                service="svc-name-that-stays",
                tool="tool-name-that-stays",
                ok=True,
                summary="x" * 100,
                args_hash="hash-that-stays",
                artifact_id="artifact-that-stays",
                as_of="2026-05-13T00:00:00Z",
            )
        )

        assert recorded["service"] == "svc-name-that-stays"
        assert recorded["tool"] == "tool-name-that-stays"
        assert recorded["args_hash"] == "hash-that-stays"
        assert recorded["artifact_id"] == "artifact-that-stays"
        assert recorded["as_of"] == "2026-05-13T00:00:00Z"

    def test_text_delta_coalescing_preserves_order(self) -> None:
        coalescer = TextDeltaCoalescer(window_ms=50)

        assert coalescer.add(
            TextDeltaEvent(
                request_id="req-1",
                session_id="sess-1",
                text="a",
                timestamp=_timestamp(0.00),
            )
        ) == []
        assert coalescer.add(
            TextDeltaEvent(
                request_id="req-1",
                session_id="sess-1",
                text="b",
                timestamp=_timestamp(0.01),
            )
        ) == []

        flushed = coalescer.add(
            TextDeltaEvent(
                request_id="req-1",
                session_id="sess-1",
                text="c",
                timestamp=_timestamp(0.10),
            )
        )

        assert [event.text for event in flushed] == ["ab"]
        assert [event.text for event in coalescer.flush()] == ["c"]
