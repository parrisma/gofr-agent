"""Tests for app.sessions.store.SessionStore."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.agent.contracts import HumanInputRequest
from app.exceptions import (
    PendingUserInputExistsError,
    SessionCapacityError,
    SessionNotFoundError,
)
from app.sessions.backend import PendingAskPayload, PendingUserInput
from app.sessions.store import Session, SessionStore


def _pending(prompt_id: str = "prompt-1") -> PendingUserInput:
    created = datetime.now(UTC)
    return PendingUserInput(
        prompt_id=prompt_id,
        run_id="run-1",
        request_id="req-1",
        human_input_request=HumanInputRequest(
            prompt_id=prompt_id,
            run_id="run-1",
            session_id="sess-1",
            prompt="Need ticker.",
            created_at=created,
            expires_at=created + timedelta(minutes=10),
            missing_fields=["ticker"],
        ),
        resume_payload=PendingAskPayload(question="Compute returns"),
        created_at=created,
        expires_at=created + timedelta(minutes=10),
    )


class TestGetOrCreate:
    async def test_none_creates_new_session(self) -> None:
        store = SessionStore()
        sess = await store.get_or_create(None)
        assert isinstance(sess, Session)
        assert sess.session_id != ""

    async def test_existing_id_returns_same_session(self) -> None:
        store = SessionStore()
        sess1 = await store.get_or_create(None)
        sess2 = await store.get_or_create(sess1.session_id)
        assert sess1 is sess2

    async def test_unknown_id_creates_new_session_with_that_id(self) -> None:
        store = SessionStore()
        sess = await store.get_or_create("no-such-id")
        assert sess.session_id == "no-such-id"

    async def test_concurrent_same_id_no_duplicates(self) -> None:
        store = SessionStore()
        sess0 = await store.get_or_create(None)
        sid = sess0.session_id

        sessions = await asyncio.gather(*(store.get_or_create(sid) for _ in range(10)))
        assert all(s is sess0 for s in sessions)
        # Only one entry in the store
        assert len(store._sessions) == 1


class TestClear:
    async def test_clear_empties_messages(self) -> None:
        store = SessionStore()
        sess = await store.get_or_create(None)
        sess.messages.append("msg1")
        await store.clear(sess.session_id)
        assert sess.messages == []
        # Session still exists
        retrieved = await store.get_or_create(sess.session_id)
        assert retrieved is sess

    async def test_clear_unknown_raises(self) -> None:
        store = SessionStore()
        with pytest.raises(SessionNotFoundError):
            await store.clear("ghost-session")

    async def test_clear_empties_summary(self) -> None:
        store = SessionStore()
        sess = await store.get_or_create(None)
        sess.messages.append("goal: keep compatibility")
        sess.summary = "Goals:\n- keep compatibility"

        await store.clear(sess.session_id)

        assert sess.messages == []
        assert sess.summary == ""

    async def test_clear_removes_pending_user_input(self) -> None:
        store = SessionStore()
        sess = await store.get_or_create("sess-1")
        await store.set_pending_user_input(sess.session_id, _pending())

        await store.clear(sess.session_id)

        assert sess.pending_user_input is None


class TestPendingUserInput:
    async def test_set_and_get_pending_user_input(self) -> None:
        store = SessionStore()
        sess = await store.get_or_create("sess-1")
        pending = _pending()

        await store.set_pending_user_input(sess.session_id, pending)

        assert await store.get_pending_user_input(sess.session_id) is pending

    async def test_set_second_pending_rejects(self) -> None:
        store = SessionStore()
        sess = await store.get_or_create("sess-1")
        await store.set_pending_user_input(sess.session_id, _pending("prompt-1"))

        with pytest.raises(PendingUserInputExistsError):
            await store.set_pending_user_input(sess.session_id, _pending("prompt-2"))

    async def test_pop_pending_user_input_matches_prompt_id(self) -> None:
        store = SessionStore()
        sess = await store.get_or_create("sess-1")
        pending = _pending("prompt-1")
        await store.set_pending_user_input(sess.session_id, pending)

        popped = await store.pop_pending_user_input(sess.session_id, "prompt-1")

        assert popped is pending
        assert sess.pending_user_input is None

    async def test_pop_pending_user_input_preserves_mismatch(self) -> None:
        store = SessionStore()
        sess = await store.get_or_create("sess-1")
        pending = _pending("prompt-1")
        await store.set_pending_user_input(sess.session_id, pending)

        popped = await store.pop_pending_user_input(sess.session_id, "prompt-2")

        assert popped is None
        assert sess.pending_user_input is pending

    async def test_clear_pending_user_input_matches_prompt_id(self) -> None:
        store = SessionStore()
        sess = await store.get_or_create("sess-1")
        await store.set_pending_user_input(sess.session_id, _pending("prompt-1"))

        cleared = await store.clear_pending_user_input(sess.session_id, "prompt-1")

        assert cleared is True
        assert sess.pending_user_input is None

    async def test_clear_pending_user_input_preserves_mismatch(self) -> None:
        store = SessionStore()
        sess = await store.get_or_create("sess-1")
        pending = _pending("prompt-1")
        await store.set_pending_user_input(sess.session_id, pending)

        cleared = await store.clear_pending_user_input(sess.session_id, "prompt-2")

        assert cleared is False
        assert sess.pending_user_input is pending


class TestDelete:
    async def test_delete_removes_session(self) -> None:
        store = SessionStore()
        sess = await store.get_or_create(None)
        await store.delete(sess.session_id)
        assert sess.session_id not in store._sessions

    async def test_delete_unknown_silent(self) -> None:
        store = SessionStore()
        await store.delete("does-not-exist")  # must not raise


class TestSweepExpired:
    async def test_removes_expired_sessions(self) -> None:
        store = SessionStore(ttl_minutes=60)
        sess = await store.get_or_create(None)
        # Back-date last_active to trigger expiry
        sess.last_active = datetime.now(UTC) - timedelta(minutes=90)

        removed = await store.sweep_expired()
        assert removed == 1
        assert sess.session_id not in store._sessions

    async def test_keeps_recent_sessions(self) -> None:
        store = SessionStore(ttl_minutes=60)
        sess = await store.get_or_create(None)
        # Explicitly set recent timestamp
        sess.last_active = datetime.now(UTC)

        removed = await store.sweep_expired()
        assert removed == 0
        assert sess.session_id in store._sessions

    async def test_mixed_expired_and_recent(self) -> None:
        store = SessionStore(ttl_minutes=60)
        old = await store.get_or_create(None)
        new = await store.get_or_create(None)

        old.last_active = datetime.now(UTC) - timedelta(minutes=120)
        new.last_active = datetime.now(UTC)

        removed = await store.sweep_expired()
        assert removed == 1
        assert old.session_id not in store._sessions
        assert new.session_id in store._sessions

    async def test_clears_expired_pending_prompt_on_live_session(self) -> None:
        store = SessionStore(ttl_minutes=60)
        sess = await store.get_or_create("sess-1")
        pending = _pending("prompt-1")
        pending.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await store.set_pending_user_input(sess.session_id, pending)

        removed = await store.sweep_expired()

        assert removed == 0
        assert sess.session_id in store._sessions
        assert sess.pending_user_input is None


class TestCapacityAndSummary:
    async def test_session_count_cap_rejects_new_sessions_clearly(self) -> None:
        store = SessionStore(max_sessions=1)
        existing = await store.get_or_create("existing")

        assert await store.get_or_create("existing") is existing
        with pytest.raises(SessionCapacityError, match="max_sessions"):
            await store.get_or_create("next-session")

    async def test_message_cap_compacts_old_messages_into_summary(self) -> None:
        store = SessionStore(max_messages_per_session=2)
        sess = await store.get_or_create(None)

        summary = sess.append_messages(
            [
                "goal: ship reasoning stream",
                "constraint: keep final answer compatibility",
                "decision: use MCP notifications",
            ]
        )

        assert summary is not None
        assert sess.messages == [
            "constraint: keep final answer compatibility",
            "decision: use MCP notifications",
        ]
        assert "Goals:" in sess.summary
        assert "goal: ship reasoning stream" in sess.summary

    async def test_recent_window_remains_intact_after_compaction(self) -> None:
        store = SessionStore(max_messages_per_session=2)
        sess = await store.get_or_create(None)

        sess.append_messages(["m1", "m2", "m3", "m4"])

        assert sess.messages == ["m3", "m4"]
        assert "m1" in sess.summary
        assert "m2" in sess.summary
