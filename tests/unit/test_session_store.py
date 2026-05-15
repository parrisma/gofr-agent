"""Tests for app.sessions.store.SessionStore."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.exceptions import SessionNotFoundError
from app.sessions.store import Session, SessionStore


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
