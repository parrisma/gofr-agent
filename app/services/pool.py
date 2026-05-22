"""Session pool for a single downstream MCP service.

Each ``SessionPool`` holds ``pool_size`` independent ``ClientSession`` connections
to the same service URL.  Callers acquire a session via the ``checkout()`` async
context manager, which blocks (via ``asyncio.Semaphore``) until a slot is
available.  Failed slots are recovered automatically by background reconnect tasks
with exponential back-off.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.exceptions import AuthTokenInvalidError, ServiceConnectionError
from app.logger import get_logger
from app.request_context import request_log_fields
from app.services import ServiceConfig

logger = get_logger("gofr-agent.pool")

_RECONNECT_DELAYS = [1, 2, 4, 8, 16, 32, 60]  # seconds, capped at 60


@asynccontextmanager
async def streamablehttp_client(
    url: str,
    headers: dict[str, str] | None = None,
) -> AsyncIterator[tuple[Any, Any, Any]]:
    """Compatibility wrapper around the current MCP Streamable HTTP client."""
    async with (
        httpx.AsyncClient(headers=headers) as http_client,
        streamable_http_client(url, http_client=http_client) as streams,
    ):
        yield streams


class SessionPool:
    """Pool of MCP ``ClientSession`` connections to a single downstream service."""

    def __init__(self, service: ServiceConfig, pool_size: int) -> None:
        self._service = service
        self._pool_size = pool_size
        self._slots: list[ClientSession | None] = [None] * pool_size
        # Keep both context managers alive so the transport stays open
        self._transport_cms: list[Any] = [None] * pool_size
        self._session_cms: list[Any] = [None] * pool_size
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(pool_size)
        self._lock: asyncio.Lock = asyncio.Lock()
        self._reconnect_tasks: list[asyncio.Task[None]] = []
        self._stopped = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Open all pool slots concurrently."""
        for index in range(self._pool_size):
            await self._open_slot(index)

    async def stop(self) -> None:
        """Close all slots and cancel reconnect tasks."""
        self._stopped = True
        reconnect_tasks = list(self._reconnect_tasks)
        for task in reconnect_tasks:
            task.cancel()
        if reconnect_tasks:
            await asyncio.gather(*reconnect_tasks, return_exceptions=True)
        self._reconnect_tasks.clear()

        async with self._lock:
            for i in range(self._pool_size):
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    if self._session_cms[i] is not None:
                        await self._session_cms[i].__aexit__(None, None, None)
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    if self._transport_cms[i] is not None:
                        await self._transport_cms[i].__aexit__(None, None, None)
                self._slots[i] = None
                self._session_cms[i] = None
                self._transport_cms[i] = None

    # ------------------------------------------------------------------
    # Checkout
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def checkout(self) -> AsyncIterator[ClientSession]:
        """Acquire a live session from the pool."""
        await self._semaphore.acquire()
        try:
            session = await self._find_live_slot()
            yield session
        finally:
            self._semaphore.release()

    @asynccontextmanager
    async def open_user_session(
        self,
        token: str,
        extra_headers: dict[str, str] | None = None,
    ) -> AsyncIterator[ClientSession]:
        """Open a one-shot session using the caller's bearer token.

        Unlike :meth:`checkout`, this does **not** use the persistent pool.
        Each call opens a fresh connection, forwards the user token, and closes
        the connection on exit.  Use this for user-driven downstream tool calls
        so that per-user tokens are never mixed with service tokens.

        Raises:
            AuthTokenInvalidError: if *token* is empty.
        """
        if not token:
            raise AuthTokenInvalidError("Bearer token required for downstream user session")
        headers = dict(extra_headers or {})
        headers["Authorization"] = f"Bearer {token}"
        async with (
            streamablehttp_client(self._service.url, headers=headers) as (r, w, _),
            ClientSession(r, w) as session,
        ):
            await session.initialize()
            yield session

    async def _find_live_slot(self) -> ClientSession:
        """Return the first live slot, waiting briefly if none is ready."""
        for _ in range(20):  # up to ~2s wait for a slot to reconnect
            async with self._lock:
                for slot in self._slots:
                    if slot is not None:
                        return slot
            await asyncio.sleep(0.1)
        raise ServiceConnectionError(
            f"No live connection available for service '{self._service.name}' "
            f"at {self._service.url}"
        )

    # ------------------------------------------------------------------
    # Internal slot management
    # ------------------------------------------------------------------

    async def _open_slot(self, index: int) -> None:
        """Open a single MCP client session in the given slot."""
        headers: dict[str, str] = {}
        if self._service.token:
            headers["Authorization"] = f"Bearer {self._service.token}"

        transport_cm = streamablehttp_client(self._service.url, headers=headers)
        try:
            read_stream, write_stream, _ = await transport_cm.__aenter__()
            session_cm = ClientSession(read_stream, write_stream)
            try:
                session = await session_cm.__aenter__()
                await session.initialize()
                async with self._lock:
                    self._slots[index] = session
                    self._transport_cms[index] = transport_cm
                    self._session_cms[index] = session_cm
                logger.debug(
                    "Pool slot opened",
                    slot=index,
                    service=self._service.name,
                    **request_log_fields(),
                )
            except Exception:
                with contextlib.suppress(Exception):
                    await session_cm.__aexit__(None, None, None)
                raise
        except Exception as exc:
            with contextlib.suppress(Exception):
                await transport_cm.__aexit__(None, None, None)
            logger.warning(
                "Failed to open pool slot",
                slot=index,
                service=self._service.name,
                error=str(exc),
                **request_log_fields(),
            )
            async with self._lock:
                self._slots[index] = None
            # Start reconnect background task
            task = asyncio.create_task(self._reconnect_loop(index))
            self._reconnect_tasks.append(task)

    async def _reconnect_loop(self, index: int) -> None:
        """Retry opening slot ``index`` with exponential back-off."""
        for delay in _RECONNECT_DELAYS:
            if self._stopped:
                return
            await asyncio.sleep(delay)
            if self._stopped:
                return
            logger.info(
                "Reconnecting pool slot",
                slot=index,
                service=self._service.name,
                **request_log_fields(),
            )
            await self._open_slot(index)
            if self._slots[index] is not None:
                logger.info(
                    "Pool slot reconnected",
                    slot=index,
                    service=self._service.name,
                    **request_log_fields(),
                )
                return
        logger.error(
            "Pool slot failed permanently after reconnect backoff",
            slot=index,
            service=self._service.name,
            **request_log_fields(),
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_healthy(self) -> bool:
        """True if at least one slot is live."""
        return any(s is not None for s in self._slots)
