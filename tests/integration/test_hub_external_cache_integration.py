"""Integration tests for the real external-cache-backed hub backend."""

from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from redis.asyncio import Redis
from redis.exceptions import RedisError

from tests.integration.conftest import AUTH_HEADERS
from tests.integration.test_analytics_hub_integration import (
    _ANALYTICS_SERVICE,
    _INSTRUMENTS_SERVICE,
    _SESSION_NAMESPACE,
    _call_tool,
    _external_cache_url,
    _fixture_hub_headers,
    _get_descriptor,
    _get_payload_from_hub,
    _local_hub_headers,
    _start_stack,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE_FILE = _REPO_ROOT / "docker/compose.dev.yml"


def _cache_client(url: str) -> Redis:
    return Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )


async def _cache_is_reachable(url: str) -> bool:
    client = _cache_client(url)
    try:
        await client.ping()
    except (RedisError, OSError):
        return False
    finally:
        with contextlib.suppress(RedisError, OSError):
            await client.aclose()
    return True


async def _wait_for_cache(url: str, *, reachable: bool, timeout: float = 15.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        if await _cache_is_reachable(url) is reachable:
            return
        if asyncio.get_running_loop().time() >= deadline:
            expected = "reachable" if reachable else "unreachable"
            raise RuntimeError(f"External cache did not become {expected}: {url}")
        await asyncio.sleep(0.2)


def _run_compose(*args: str) -> None:
    result = subprocess.run(
        ["docker", "compose", "-f", str(_COMPOSE_FILE), *args],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "docker compose failed"
        raise RuntimeError(detail)


async def _flush_cache(url: str) -> None:
    client = _cache_client(url)
    try:
        await client.flushdb()
    finally:
        with contextlib.suppress(RedisError, OSError):
            await client.aclose()


@pytest.fixture()
async def external_cache_url() -> str:
    url = _external_cache_url()
    if not await _cache_is_reachable(url):
        try:
            _run_compose("up", "-d", "valkey")
            await _wait_for_cache(url, reachable=True)
        except (FileNotFoundError, RuntimeError) as exc:
            pytest.skip(f"External cache integration requires Valkey: {exc}")

    await _flush_cache(url)
    try:
        yield url
    finally:
        if not await _cache_is_reachable(url):
            with contextlib.suppress(RuntimeError):
                _run_compose("up", "-d", "valkey")
            with contextlib.suppress(RuntimeError):
                await _wait_for_cache(url, reachable=True, timeout=10.0)
        if await _cache_is_reachable(url):
            with contextlib.suppress(RedisError, OSError):
                await _flush_cache(url)


async def _store_result(
    stack,
    *,
    session_namespace: str,
    payload: list[dict[str, Any]] | None = None,
    summary: str = "external cache test payload",
) -> tuple[bool, str]:
    return await _call_tool(
        stack.local_hub_url,
        "_store_result",
        {
            "protocol_version": 1,
            "producer_service": _INSTRUMENTS_SERVICE,
            "producer_tool": "get_ohlcv_history",
            "result_type": "ohlcv_bars",
            "schema_id": "gofr.ohlcv_bars.v1",
            "payload": payload or [{"date": "2026-05-13", "close": 182.917}],
            "summary": summary,
        },
        headers=_local_hub_headers(
            service=_INSTRUMENTS_SERVICE,
            session_namespace=session_namespace,
            allowed_operations=("store",),
        ),
    )


async def _get_result(
    stack,
    descriptor: dict[str, Any],
    *,
    session_namespace: str,
) -> tuple[bool, str]:
    return await _call_tool(
        stack.local_hub_url,
        "_get_result",
        {
            "protocol_version": 1,
            "result_guid": descriptor["result_guid"],
            "hub_service": descriptor["hub_service"],
            "expected_result_type": "ohlcv_bars",
            "expected_schema_id": "gofr.ohlcv_bars.v1",
        },
        headers=_local_hub_headers(
            service=_ANALYTICS_SERVICE,
            session_namespace=session_namespace,
            allowed_operations=("get",),
        ),
    )


async def _describe_result(
    stack,
    descriptor: dict[str, Any],
    *,
    session_namespace: str,
) -> tuple[bool, str]:
    return await _call_tool(
        stack.local_hub_url,
        "_describe_result",
        {
            "protocol_version": 1,
            "result_guid": descriptor["result_guid"],
            "hub_service": descriptor["hub_service"],
            "expected_result_type": "ohlcv_bars",
            "expected_schema_id": "gofr.ohlcv_bars.v1",
        },
        headers=_local_hub_headers(
            service=_ANALYTICS_SERVICE,
            session_namespace=session_namespace,
            allowed_operations=("describe",),
        ),
    )


@pytest.mark.asyncio
class TestHubExternalCacheIntegration:
    async def test_external_cache_round_trip_matches_inline(self, external_cache_url: str) -> None:
        stack = await _start_stack(
            hub_store_backend="external_cache",
            hub_cache_url=external_cache_url,
        )

        try:
            descriptor = await _get_descriptor(stack)
            payload = await _get_payload_from_hub(stack, descriptor)
            health = await stack.result_store.health()

            descriptor_error, descriptor_raw = await _call_tool(
                stack.analytics_url,
                "simple_return",
                {"ticker": "MSFT", "bars_ref": descriptor},
                headers=_fixture_hub_headers(
                    stack,
                    service=_ANALYTICS_SERVICE,
                    session_namespace=_SESSION_NAMESPACE,
                    allowed_operations=("get", "describe"),
                ),
            )
            inline_error, inline_raw = await _call_tool(
                stack.analytics_url,
                "simple_return",
                {"ticker": "MSFT", "bars": payload},
                headers=AUTH_HEADERS,
            )

            assert health.backend == "external_cache"
            assert health.reachable is True
            assert descriptor_error is False, descriptor_raw
            assert inline_error is False, inline_raw
            assert json.loads(descriptor_raw) == json.loads(inline_raw)
        finally:
            await stack.shutdown()

    async def test_cross_session_replay_returns_unknown_result(
        self,
        external_cache_url: str,
    ) -> None:
        stack = await _start_stack(
            hub_store_backend="external_cache",
            hub_cache_url=external_cache_url,
        )

        try:
            descriptor = await _get_descriptor(stack)
            describe_error, describe_raw = await _describe_result(
                stack,
                descriptor,
                session_namespace="other-session",
            )
            fetch_error, fetch_raw = await _get_result(
                stack,
                descriptor,
                session_namespace="other-session",
            )

            assert describe_error is True
            assert fetch_error is True
            assert "hub.unknown_result" in describe_raw
            assert "hub.unknown_result" in fetch_raw
        finally:
            await stack.shutdown()

    async def test_expired_descriptor_returns_expired_result(self, external_cache_url: str) -> None:
        stack = await _start_stack(
            hub_store_backend="external_cache",
            hub_cache_url=external_cache_url,
            hub_default_ttl_seconds=1,
        )

        try:
            descriptor = await _get_descriptor(stack)
            await asyncio.sleep(1.2)
            is_error, raw = await _get_result(
                stack,
                descriptor,
                session_namespace=_SESSION_NAMESPACE,
            )

            assert is_error is True
            assert "hub.expired_result" in raw
        finally:
            await stack.shutdown()

    async def test_cache_flush_returns_unknown_result(self, external_cache_url: str) -> None:
        stack = await _start_stack(
            hub_store_backend="external_cache",
            hub_cache_url=external_cache_url,
        )

        try:
            descriptor = await _get_descriptor(stack)
            await _flush_cache(external_cache_url)
            describe_error, describe_raw = await _describe_result(
                stack,
                descriptor,
                session_namespace=_SESSION_NAMESPACE,
            )
            fetch_error, fetch_raw = await _get_result(
                stack,
                descriptor,
                session_namespace=_SESSION_NAMESPACE,
            )

            assert describe_error is True
            assert fetch_error is True
            assert "hub.unknown_result" in describe_raw
            assert "hub.unknown_result" in fetch_raw
        finally:
            await stack.shutdown()

    async def test_capacity_pressure_returns_capacity_exceeded(
        self,
        external_cache_url: str,
    ) -> None:
        stack = await _start_stack(
            hub_store_backend="external_cache",
            hub_cache_url=external_cache_url,
            hub_max_results=1,
        )

        try:
            first_error, first_raw = await _store_result(
                stack,
                session_namespace="capacity-session",
                summary="first descriptor",
            )
            second_error, second_raw = await _store_result(
                stack,
                session_namespace="capacity-session",
                summary="second descriptor",
            )

            assert first_error is False, first_raw
            assert second_error is True
            assert "hub.capacity_exceeded" in second_raw
        finally:
            await stack.shutdown()

    async def test_store_outage_returns_store_unavailable(
        self,
        external_cache_url: str,
    ) -> None:
        stack = await _start_stack(
            hub_store_backend="external_cache",
            hub_cache_url=external_cache_url,
            hub_cache_max_attempts=1,
            hub_cache_connect_timeout_seconds=0.25,
            hub_cache_operation_timeout_seconds=0.25,
            hub_cache_retry_backoff_seconds=0,
            hub_cache_request_budget_seconds=0.25,
        )

        try:
            _run_compose("stop", "valkey")
            await _wait_for_cache(external_cache_url, reachable=False, timeout=10.0)
            is_error, raw = await _store_result(
                stack,
                session_namespace="outage-session",
                summary="cache outage",
            )

            assert is_error is True
            assert "hub.store_unavailable" in raw
        finally:
            _run_compose("up", "-d", "valkey")
            await _wait_for_cache(external_cache_url, reachable=True, timeout=10.0)
            await stack.shutdown()
