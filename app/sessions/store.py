"""In-memory session store with TTL sweep."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.exceptions import SessionNotFoundError

logger = logging.getLogger(__name__)

_SWEEP_INTERVAL_SECS = 60


@dataclass
class Session:
    """A single conversation session."""

    session_id: str
    messages: list[Any] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_active: datetime = field(default_factory=lambda: datetime.now(UTC))


class SessionStore:
    """Thread-safe in-memory store for :class:`Session` objects."""

    def __init__(self, ttl_minutes: int = 60) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        self._ttl_minutes = ttl_minutes
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
            if session_id is not None and session_id in self._sessions:
                sess = self._sessions[session_id]
                sess.last_active = datetime.now(UTC)
                return sess
            # Determine the ID to use
            new_id = session_id if session_id is not None else str(uuid.uuid4())
            sess = Session(session_id=new_id)
            self._sessions[new_id] = sess
            return sess

    async def clear(self, session_id: str) -> None:
        """Empty the message history of a session, keeping the session alive."""
        async with self._lock:
            if session_id not in self._sessions:
                raise SessionNotFoundError(f"Session '{session_id}' not found.")
            self._sessions[session_id].messages = []
            self._sessions[session_id].last_active = datetime.now(UTC)

    async def delete(self, session_id: str) -> None:
        """Remove a session entirely."""
        async with self._lock:
            self._sessions.pop(session_id, None)

    # ------------------------------------------------------------------
    # TTL sweep
    # ------------------------------------------------------------------

    async def sweep_expired(self) -> int:
        """Remove sessions idle longer than the TTL.

        Returns the number of sessions removed.
        """
        cutoff = datetime.now(UTC) - timedelta(minutes=self._ttl_minutes)
        async with self._lock:
            expired = [
                sid
                for sid, sess in self._sessions.items()
                if sess.last_active < cutoff
            ]
            for sid in expired:
                del self._sessions[sid]
        if expired:
            logger.info("Swept %d expired session(s).", len(expired))
        return len(expired)

    async def start_ttl_sweep(self) -> None:
        """Start a background task that calls :meth:`sweep_expired` every 60s."""
        self._sweep_task = asyncio.create_task(self._sweep_loop())

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(_SWEEP_INTERVAL_SECS)
            await self.sweep_expired()
