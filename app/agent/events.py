"""Typed reasoning events and collection helpers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, TypeAlias
from uuid import uuid4

from pydantic import BaseModel, Field

StepKind: TypeAlias = Literal[
    "thought",
    "tool_call",
    "tool_result",
    "summary",
    "final_answer",
]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class BaseReasoningEvent(BaseModel):
    request_id: str
    session_id: str
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    sequence: int = 0
    kind: str
    timestamp: datetime = Field(default_factory=_utc_now)
    truncated: bool = False


class RunStartedEvent(BaseReasoningEvent):
    kind: Literal["run_started"] = "run_started"
    question: str | None = None


class StepStartedEvent(BaseReasoningEvent):
    kind: Literal["step_started"] = "step_started"
    step_kind: StepKind
    title: str | None = None


class TextDeltaEvent(BaseReasoningEvent):
    kind: Literal["text_delta"] = "text_delta"
    text: str


class ToolCallEvent(BaseReasoningEvent):
    kind: Literal["tool_call"] = "tool_call"
    service: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    attempt: int = 1


class ToolRetryEvent(BaseReasoningEvent):
    kind: Literal["tool_retry"] = "tool_retry"
    service: str
    tool: str
    attempt: int
    message: str | None = None


class ToolResultEvent(BaseReasoningEvent):
    kind: Literal["tool_result"] = "tool_result"
    service: str
    tool: str
    ok: bool
    summary: Any
    attempt: int = 1
    latency_ms: int | None = None


class SummaryUpdateEvent(BaseReasoningEvent):
    kind: Literal["summary_update"] = "summary_update"
    summary: str


class StepCompletedEvent(BaseReasoningEvent):
    kind: Literal["step_completed"] = "step_completed"
    step_kind: StepKind
    status: Literal["ok", "error"] = "ok"


class RunCompletedEvent(BaseReasoningEvent):
    kind: Literal["run_completed"] = "run_completed"
    model: str | None = None
    answer_preview: str | None = None
    tokens_used: int | None = None


class RunFailedEvent(BaseReasoningEvent):
    kind: Literal["run_failed"] = "run_failed"
    error: str
    fatal: bool = True


ReasoningEvent: TypeAlias = (
    RunStartedEvent
    | StepStartedEvent
    | TextDeltaEvent
    | ToolCallEvent
    | ToolRetryEvent
    | ToolResultEvent
    | SummaryUpdateEvent
    | StepCompletedEvent
    | RunCompletedEvent
    | RunFailedEvent
)


def _truncate_value(value: Any, max_chars: int) -> tuple[Any, bool]:
    if isinstance(value, str):
        if len(value) <= max_chars:
            return value, False
        return value[:max_chars] + "...[truncated]", True
    if isinstance(value, list):
        truncated_any = False
        truncated_items: list[Any] = []
        for item in value:
            truncated_item, changed = _truncate_value(item, max_chars)
            truncated_items.append(truncated_item)
            truncated_any = truncated_any or changed
        return truncated_items, truncated_any
    if isinstance(value, dict):
        truncated_any = False
        truncated_dict: dict[str, Any] = {}
        for key, item in value.items():
            truncated_item, changed = _truncate_value(item, max_chars)
            truncated_dict[key] = truncated_item
            truncated_any = truncated_any or changed
        return truncated_dict, truncated_any
    return value, False


class EventCollector:
    """Collect reasoning events and derive a bounded final steps list."""

    def __init__(
        self,
        request_id: str,
        session_id: str,
        *,
        max_payload_chars: int = 4000,
        max_response_steps: int = 200,
    ) -> None:
        self.request_id = request_id
        self.session_id = session_id
        self.max_payload_chars = max_payload_chars
        self.max_response_steps = max_response_steps
        self._sequence = 0
        self._events: list[dict[str, Any]] = []

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    def record(self, event: ReasoningEvent) -> dict[str, Any]:
        self._sequence += 1
        serialised = event.model_copy(
            update={
                "request_id": self.request_id,
                "session_id": self.session_id,
                "sequence": self._sequence,
            }
        ).model_dump(mode="json")

        serialised, truncated = _truncate_value(serialised, self.max_payload_chars)
        if truncated:
            serialised["truncated"] = True
        self._events.append(serialised)
        return serialised

    def build_steps(self) -> list[dict[str, Any]]:
        step_events = [event for event in self._events if event["kind"] != "text_delta"]
        return step_events[-self.max_response_steps :]


class TextDeltaCoalescer:
    """Merge adjacent text deltas within a short time window."""

    def __init__(self, window_ms: int = 50) -> None:
        self._window = timedelta(milliseconds=window_ms)
        self._pending: TextDeltaEvent | None = None

    def add(self, event: TextDeltaEvent) -> list[TextDeltaEvent]:
        if self._pending is None:
            self._pending = event
            return []

        if event.timestamp - self._pending.timestamp <= self._window:
            self._pending = self._pending.model_copy(
                update={
                    "text": self._pending.text + event.text,
                    "timestamp": event.timestamp,
                }
            )
            return []

        flushed = self._pending
        self._pending = event
        return [flushed]

    def flush(self) -> list[TextDeltaEvent]:
        if self._pending is None:
            return []
        flushed = self._pending
        self._pending = None
        return [flushed]


class EventSink:
    """Collect events and optionally forward them to a notifier."""

    def __init__(
        self,
        collector: EventCollector,
        notifier: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self.collector = collector
        self._notifier = notifier

    async def emit(self, event: ReasoningEvent) -> dict[str, Any]:
        serialised = self.collector.record(event)
        if self._notifier is not None:
            await self._notifier(serialised)
        return serialised

    def build_steps(self) -> list[dict[str, Any]]:
        return self.collector.build_steps()
