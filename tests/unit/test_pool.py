"""Tests for app.services.pool.SessionPool."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import AuthTokenInvalidError, ServiceConnectionError
from app.services import ServiceConfig
from app.services.pool import SessionPool


def _make_service(name: str = "test-svc", url: str = "http://test/mcp") -> ServiceConfig:
    return ServiceConfig(name=name, url=url)


def _make_fake_session() -> MagicMock:
    session = MagicMock()
    session.initialize = AsyncMock()
    return session


async def _start_pool_with_sessions(
    pool: SessionPool, sessions: list[MagicMock]
) -> None:
    """Start a pool with pre-supplied sessions (no real network calls)."""

    call_idx = [0]

    async def fake_open_slot(index: int) -> None:
        pool._slots[index] = sessions[call_idx[0] % len(sessions)]
        pool._transport_cms[index] = MagicMock()
        pool._session_cms[index] = MagicMock()
        call_idx[0] += 1

    with patch.object(pool, "_open_slot", side_effect=fake_open_slot):
        await pool.start()


class TestSessionPoolStart:
    async def test_start_opens_pool_size_connections(self) -> None:
        svc = _make_service()
        pool = SessionPool(svc, pool_size=3)
        sessions = [_make_fake_session() for _ in range(3)]
        await _start_pool_with_sessions(pool, sessions)
        live = [s for s in pool._slots if s is not None]
        assert len(live) == 3
        await pool.stop()

    async def test_is_healthy_true_after_start(self) -> None:
        svc = _make_service()
        pool = SessionPool(svc, pool_size=2)
        sessions = [_make_fake_session() for _ in range(2)]
        await _start_pool_with_sessions(pool, sessions)
        assert pool.is_healthy is True
        await pool.stop()

    async def test_is_healthy_false_before_start(self) -> None:
        pool = SessionPool(_make_service(), pool_size=2)
        assert pool.is_healthy is False


class TestSessionPoolCheckout:
    async def test_checkout_yields_session(self) -> None:
        svc = _make_service()
        pool = SessionPool(svc, pool_size=1)
        session = _make_fake_session()
        await _start_pool_with_sessions(pool, [session])

        async with pool.checkout() as s:
            assert s is session

        await pool.stop()

    async def test_concurrent_checkouts_up_to_pool_size(self) -> None:
        pool_size = 3
        svc = _make_service()
        pool = SessionPool(svc, pool_size=pool_size)
        sessions = [_make_fake_session() for _ in range(pool_size)]
        await _start_pool_with_sessions(pool, sessions)

        results: list[object] = []

        async def _use() -> None:
            async with pool.checkout() as s:
                await asyncio.sleep(0.01)
                results.append(s)

        await asyncio.gather(*[_use() for _ in range(pool_size)])
        assert len(results) == pool_size
        await pool.stop()

    async def test_pool_plus_one_concurrent_waits(self) -> None:
        """pool_size+1 concurrent checkouts: the last one must wait."""
        pool_size = 2
        svc = _make_service()
        pool = SessionPool(svc, pool_size=pool_size)
        sessions = [_make_fake_session() for _ in range(pool_size)]
        await _start_pool_with_sessions(pool, sessions)

        entered: list[int] = []

        async def _slow_use(task_id: int) -> None:
            async with pool.checkout():
                entered.append(task_id)
                await asyncio.sleep(0.05)

        tasks = [asyncio.create_task(_slow_use(i)) for i in range(pool_size + 1)]
        # Give the first pool_size tasks time to enter
        await asyncio.sleep(0.01)
        assert len(entered) == pool_size  # third task is waiting

        await asyncio.gather(*tasks)
        assert len(entered) == pool_size + 1
        await pool.stop()

    async def test_checkout_raises_when_no_live_slots(self) -> None:
        pool = SessionPool(_make_service(), pool_size=1)
        # Force the semaphore to allow entry but leave slots empty
        pool._semaphore = asyncio.Semaphore(10)
        with pytest.raises(ServiceConnectionError):
            async with pool.checkout():
                pass


class TestSessionPoolStop:
    async def test_stop_clears_all_slots(self) -> None:
        svc = _make_service()
        pool = SessionPool(svc, pool_size=2)
        sessions = [_make_fake_session() for _ in range(2)]
        await _start_pool_with_sessions(pool, sessions)

        assert pool.is_healthy is True
        await pool.stop()
        assert all(s is None for s in pool._slots)

    async def test_reconnect_loop_not_started_when_all_slots_open(self) -> None:
        svc = _make_service()
        pool = SessionPool(svc, pool_size=2)
        sessions = [_make_fake_session() for _ in range(2)]
        await _start_pool_with_sessions(pool, sessions)

        assert pool._reconnect_tasks == []
        await pool.stop()


class TestSessionPoolOpenSlot:
    """Unit tests for the actual MCP client setup in _open_slot."""

    async def test_open_slot_populates_slot_on_success(self) -> None:
        pool = SessionPool(_make_service(), pool_size=1)
        session = _make_fake_session()

        transport_cm = MagicMock()
        transport_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock(), None))
        transport_cm.__aexit__ = AsyncMock(return_value=False)

        session_cm = MagicMock()
        session_cm.__aenter__ = AsyncMock(return_value=session)
        session_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.pool.streamablehttp_client", return_value=transport_cm),
            patch("app.services.pool.ClientSession", return_value=session_cm),
        ):
            await pool._open_slot(0)

        assert pool._slots[0] is session
        assert not pool._reconnect_tasks

    async def test_open_slot_starts_reconnect_on_failure(self) -> None:
        pool = SessionPool(_make_service(), pool_size=1)
        pool._stopped = True  # prevent reconnect from actually sleeping

        transport_cm = MagicMock()
        transport_cm.__aenter__ = AsyncMock(side_effect=OSError("refused"))
        transport_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.pool.streamablehttp_client", return_value=transport_cm):
            await pool._open_slot(0)

        assert pool._slots[0] is None
        # A reconnect task was created (though it exited immediately because _stopped=True)
        assert len(pool._reconnect_tasks) == 1
        await asyncio.gather(*pool._reconnect_tasks)


class TestOpenUserSession:
    """Tests for the one-shot per-user session opener."""

    async def test_open_user_session_uses_token_header(self) -> None:
        """The bearer token is forwarded as Authorization header."""
        pool = SessionPool(_make_service(), pool_size=1)
        session = _make_fake_session()

        transport_cm = MagicMock()
        transport_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock(), None))
        transport_cm.__aexit__ = AsyncMock(return_value=False)

        session_cm = MagicMock()
        session_cm.__aenter__ = AsyncMock(return_value=session)
        session_cm.__aexit__ = AsyncMock(return_value=False)

        mock_shttp = patch(
            "app.services.pool.streamablehttp_client", return_value=transport_cm
        )
        with (
            mock_shttp as mock_http,
            patch("app.services.pool.ClientSession", return_value=session_cm),
        ):
            async with pool.open_user_session("my-jwt") as s:
                assert s is session

        called_kwargs = mock_http.call_args.kwargs
        assert called_kwargs.get("headers", {}).get("Authorization") == "Bearer my-jwt"

    async def test_open_user_session_empty_token_raises(self) -> None:
        pool = SessionPool(_make_service(), pool_size=1)
        with pytest.raises(AuthTokenInvalidError):
            async with pool.open_user_session(""):
                pass  # pragma: no cover

    async def test_checkout_still_works(self) -> None:
        """Adding open_user_session must not break checkout()."""
        pool = SessionPool(_make_service(), pool_size=1)
        session = _make_fake_session()
        await _start_pool_with_sessions(pool, [session])
        async with pool.checkout() as s:
            assert s is session
