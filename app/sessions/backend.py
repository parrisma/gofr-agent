"""Session backend abstractions and in-memory session state."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from app.agent.contracts import HumanInputRequest


def _utc_now() -> datetime:
    return datetime.now(UTC)


_SUMMARY_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Goals", ("goal", "objective", "need to", "want to")),
    ("Constraints", ("constraint", "must", "limit", "cap", "requirement")),
    ("Decisions", ("decision", "decided", "selected", "chose", "choose")),
    ("Open tasks", ("open task", "todo", "next step", "remaining", "follow-up")),
    (
        "Important tool findings",
        ("tool", "found", "lookup", "result", "returned", "observation"),
    ),
    ("User preferences", ("preference", "prefer", "avoid", "please")),
    ("Unresolved errors", ("error", "failed", "exception", "timeout", "issue")),
)
_MAX_SUMMARY_LINES_PER_SECTION = 6


def _message_text(message: Any) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, bytes):
        return message.decode("utf-8", errors="replace")
    if hasattr(message, "model_dump"):
        try:
            dumped = message.model_dump(mode="json")
            return json.dumps(dumped, sort_keys=True)
        except TypeError:
            pass
    if isinstance(message, dict):
        return json.dumps(message, sort_keys=True, default=str)
    parts = getattr(message, "parts", None)
    if isinstance(parts, list):
        rendered_parts: list[str] = []
        for part in parts:
            content = getattr(part, "content", None)
            if isinstance(content, str):
                rendered_parts.append(content)
                continue
            text = getattr(part, "text", None)
            if isinstance(text, str):
                rendered_parts.append(text)
        if rendered_parts:
            return "\n".join(rendered_parts)
    return str(message)


def _summary_source_lines(existing_summary: str, compacted_messages: Iterable[Any]) -> list[str]:
    lines: list[str] = []
    if existing_summary:
        for raw_line in existing_summary.splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.endswith(":"):
                continue
            if stripped.startswith("-"):
                stripped = stripped[1:].strip()
            if stripped and stripped.lower() != "none":
                lines.append(stripped)

    for message in compacted_messages:
        for raw_line in _message_text(message).splitlines():
            stripped = raw_line.strip()
            if stripped:
                lines.append(stripped)
    return lines


def build_session_summary(existing_summary: str, compacted_messages: Iterable[Any]) -> str:
    buckets: dict[str, list[str]] = {
        title: [] for title, _keywords in _SUMMARY_SECTIONS
    }

    for line in _summary_source_lines(existing_summary, compacted_messages):
        lower_line = line.lower()
        matched_title: str | None = None
        for title, keywords in _SUMMARY_SECTIONS:
            if any(keyword in lower_line for keyword in keywords):
                matched_title = title
                break
        target_title = matched_title or "Goals"
        current = buckets[target_title]
        if line not in current and len(current) < _MAX_SUMMARY_LINES_PER_SECTION:
            current.append(line)

    sections: list[str] = []
    for title, _keywords in _SUMMARY_SECTIONS:
        entries = buckets[title] or ["None"]
        rendered = "\n".join(f"- {entry}" for entry in entries)
        sections.append(f"{title}:\n{rendered}")
    return "\n\n".join(sections)


@dataclass
class PendingAskPayload:
    """Original ask parameters needed to resume a Phase 1A prompt."""

    question: str
    context: str | None = None
    instructions: str | None = None
    asserted_facts: list[str] | None = None
    pasted_content: list[str] | None = None
    forbidden_services: list[str] | None = None
    forbidden_tools: list[str] | None = None
    allowed_services: list[str] | None = None
    tools_only: bool | None = None
    output_format: str | None = None
    no_commentary: bool | None = None
    max_steps: int = 10
    model_override: str | None = None


@dataclass
class PendingUserInput:
    """One unresolved human-input prompt for a session."""

    prompt_id: str
    run_id: str
    request_id: str
    human_input_request: HumanInputRequest
    resume_payload: PendingAskPayload
    created_at: datetime
    expires_at: datetime
    subject: str | None = None


@dataclass
class Session:
    """A single conversation session."""

    session_id: str
    max_messages_per_session: int = 100
    messages: list[Any] = field(default_factory=list)
    summary: str = ""
    pending_user_input: PendingUserInput | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    last_active: datetime = field(default_factory=_utc_now)

    def touch(self) -> None:
        now = _utc_now()
        self.updated_at = now
        self.last_active = now

    def clear(self) -> None:
        self.messages = []
        self.summary = ""
        self.pending_user_input = None
        self.touch()

    def append_messages(self, new_messages: list[Any]) -> str | None:
        if new_messages:
            self.messages.extend(new_messages)
        self.touch()
        return self._compact_if_needed()

    def _compact_if_needed(self) -> str | None:
        message_limit = max(1, self.max_messages_per_session)
        if len(self.messages) <= message_limit:
            return None

        compacted = self.messages[:-message_limit]
        self.messages = self.messages[-message_limit:]
        next_summary = build_session_summary(self.summary, compacted)
        if next_summary == self.summary:
            return None
        self.summary = next_summary
        return self.summary


class SessionBackend(Protocol):
    """Minimal async session backend contract."""

    async def get(self, session_id: str) -> Session | None:
        """Return a session by id if present."""
        raise NotImplementedError

    async def put(self, session: Session) -> None:
        """Store or replace a session."""
        raise NotImplementedError

    async def delete(self, session_id: str) -> None:
        """Delete a session if present."""
        raise NotImplementedError

    async def values(self) -> list[Session]:
        """Return all sessions."""
        raise NotImplementedError

    async def count(self) -> int:
        """Return the number of stored sessions."""
        raise NotImplementedError


class InMemorySessionBackend:
    """Default in-memory session backend."""

    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}

    async def get(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    async def put(self, session: Session) -> None:
        self.sessions[session.session_id] = session

    async def delete(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)

    async def values(self) -> list[Session]:
        return list(self.sessions.values())

    async def count(self) -> int:
        return len(self.sessions)
