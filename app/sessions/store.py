"""Session store with TTL sweep and bounded in-memory history."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from app.exceptions import SessionCapacityError, SessionNotFoundError
from app.logger import get_logger
from app.request_context import request_log_fields
from app.sessions.backend import InMemorySessionBackend, Session, SessionBackend

logger = get_logger("gofr-agent.sessions")


class SessionStore:
    """Thread-safe in-memory store for :class:`Session` objects."""

    def __init__(
        self,
        ttl_minutes: int = 60,
        *,
        max_sessions: int = 1000,
        max_messages_per_session: int = 100,
        sweep_interval_seconds: int = 60,
        backend: SessionBackend | None = None,
    ) -> None:
        self._backend = backend or InMemorySessionBackend()
        if isinstance(self._backend, InMemorySessionBackend):
            self._sessions = self._backend.sessions
        else:
            self._sessions: dict[str, Session] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        self._ttl_minutes = ttl_minutes
        self._max_sessions = max(1, max_sessions)
        self._max_messages_per_session = max(1, max_messages_per_session)
        self._sweep_interval_seconds = max(1, sweep_interval_seconds)
        self._sweep_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def get_or_create(self, session_id: str | None) -> Session:
        """Return an existing session or create a new one.

        If *session_id* is provided but not yet in the store, a new session is
        created and stored under that ID.  If *session_id* is ``None``, a
        brand-new session with a generated UUID is created.
        """
        async with self._lock:
            if session_id is not None:
                existing = await self._backend.get(session_id)
                if existing is not None:
                    existing.touch()
                    return existing

            if await self._backend.count() >= self._max_sessions:
                raise SessionCapacityError(
                    f"Cannot create session; max_sessions ({self._max_sessions}) reached."
                )

            new_id = session_id if session_id is not None else str(uuid.uuid4())
            sess = Session(
                session_id=new_id,
                max_messages_per_session=self._max_messages_per_session,
            )
            await self._backend.put(sess)
            return sess

    async def clear(self, session_id: str) -> None:
        """Empty the message history of a session, keeping the session alive."""
        async with self._lock:
            session = await self._backend.get(session_id)
            if session is None:
                raise SessionNotFoundError(f"Session '{session_id}' not found.")
        async with session.lock:
            session.clear()

    async def delete(self, session_id: str) -> None:
        """Remove a session entirely."""
        async with self._lock:
            await self._backend.delete(session_id)

    # ------------------------------------------------------------------
    # TTL sweep
    # ------------------------------------------------------------------

    async def sweep_expired(self) -> int:
        """Remove sessions idle longer than the TTL.

        Returns the number of sessions removed.
        """
        cutoff = datetime.now(UTC) - timedelta(minutes=self._ttl_minutes)
        async with self._lock:
            sessions = await self._backend.values()
            expired = [
                sess.session_id
                for sess in sessions
                if sess.last_active < cutoff
            ]
            for sid in expired:
                await self._backend.delete(sid)
        if expired:
            logger.info(
                "Swept expired sessions",
                expired_count=len(expired),
                **request_log_fields(),
            )
        return len(expired)

    async def start_ttl_sweep(self) -> None:
        """Start a background task that calls :meth:`sweep_expired` every 60s."""
        self._sweep_task = asyncio.create_task(self._sweep_loop())

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(self._sweep_interval_seconds)
            await self.sweep_expired()
