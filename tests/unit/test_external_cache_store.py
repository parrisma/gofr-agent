from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.config import GofrAgentConfig
from app.hub.clock import Clock
from app.hub.errors import (
    HUB_CAPACITY_EXCEEDED,
    HUB_EXPIRED_RESULT,
    HUB_OVERSIZED_RESULT,
    HUB_STORE_UNAVAILABLE,
    HUB_UNKNOWN_RESULT,
    HubError,
)
from app.hub.external_cache_client import (
    ExternalCacheCapacityExceededError,
    ExternalCacheUnavailableError,
)
from app.hub.external_cache_store import ExternalCacheResultStore
from app.hub.models import DescribeResultRequest, GetResultRequest, StoreResultRequest
from app.hub.store_types import HubAccessScope


class _FakeClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def utcnow(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._now.timestamp()

    def advance(self, seconds: int) -> None:
        self._now += timedelta(seconds=seconds)


class _FakeExternalCacheClient:
    def __init__(self) -> None:
        self.meta: dict[str, str] = {}
        self.payload: dict[str, str] = {}
        self.indices: dict[str, dict[str, float]] = {}
        self.failure_counts: dict[str, int] = {}

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        failures_remaining = self.failure_counts.get("stop", 0)
        if failures_remaining > 0:
            self.failure_counts["stop"] = failures_remaining - 1
            raise ExternalCacheUnavailableError("stop failed")
        return None

    async def ping(self) -> bool:
        return True

    async def count_indexed_results(self, *, key_prefix: str) -> int:
        total = 0
        for key, members in self.indices.items():
            if key.startswith(f"{key_prefix}:session:"):
                total += len(members)
        return total

    async def atomic_store_record(
        self,
        *,
        meta_key: str,
        payload_key: str,
        index_key: str,
        result_guid: str,
        meta_json: str,
        payload_json: str,
        expires_at_timestamp: float,
        now_timestamp: float,
        ttl_seconds: int,
        max_results: int,
    ) -> None:
        del ttl_seconds
        failures_remaining = self.failure_counts.get("atomic_store_record", 0)
        if failures_remaining > 0:
            self.failure_counts["atomic_store_record"] = failures_remaining - 1
            raise ExternalCacheUnavailableError("atomic store failed")

        index = self.indices.setdefault(index_key, {})
        expired = [guid for guid, score in index.items() if score <= now_timestamp]
        for guid in expired:
            del index[guid]
        if len(index) >= max_results:
            raise ExternalCacheCapacityExceededError("capacity reached")

        self.meta[meta_key] = meta_json
        self.payload[payload_key] = payload_json
        index[result_guid] = expires_at_timestamp

    async def prune_expired(
        self,
        *,
        index_key: str,
        before_timestamp: float,
    ) -> tuple[str, ...]:
        index = self.indices.setdefault(index_key, {})
        expired = tuple(guid for guid, score in list(index.items()) if score <= before_timestamp)
        for guid in expired:
            del index[guid]
        return expired

    async def read_record(
        self,
        *,
        meta_key: str,
        payload_key: str,
    ) -> tuple[str | None, str | None]:
        failures_remaining = self.failure_counts.get("read_record", 0)
        if failures_remaining > 0:
            self.failure_counts["read_record"] = failures_remaining - 1
            raise ExternalCacheUnavailableError("read failed")
        return self.meta.get(meta_key), self.payload.get(payload_key)

    async def remove_index_member(self, *, index_key: str, result_guid: str) -> None:
        self.indices.setdefault(index_key, {}).pop(result_guid, None)

    async def delete_keys(self, *keys: str) -> None:
        for key in keys:
            self.meta.pop(key, None)
            self.payload.pop(key, None)


def _config(**overrides: Any) -> GofrAgentConfig:
    defaults: dict[str, Any] = {
        "hub_store_backend": "external_cache",
        "hub_cache_url": "redis://gofr-agent-valkey:6379/0",
        "hub_default_ttl_seconds": 30,
        "hub_max_payload_bytes": 2048,
        "hub_max_results": 2,
        "hub_cache_max_attempts": 2,
        "hub_cache_retry_backoff_seconds": 0,
        "hub_cache_request_budget_seconds": 5,
    }
    defaults.update(overrides)
    return GofrAgentConfig(**defaults)


def _scope(
    session_namespace: str,
    *,
    session_id: str = "raw-session-id",
) -> HubAccessScope:
    return HubAccessScope(
        session_namespace=session_namespace,
        principal_service="analytics",
        allowed_operations=("store", "get", "describe"),
        allowed_result_types=("ohlcv_bars",),
        session_id=session_id,
        request_id="request-1",
    )


def _store_request(**overrides: Any) -> StoreResultRequest:
    payload = [{"date": "2026-05-16", "close": 100.0}]
    defaults = {
        "protocol_version": 1,
        "producer_service": "analytics",
        "producer_tool": "publish_prices",
        "result_type": "ohlcv_bars",
        "schema_id": "gofr.ohlcv_bars.v1",
        "payload": payload,
        "summary": "one bar",
        "source_args": {"ticker": "AAPL"},
        "ttl_seconds": 30,
    }
    defaults.update(overrides)
    return StoreResultRequest(**defaults)


def _get_request(result_guid: str) -> GetResultRequest:
    return GetResultRequest(
        protocol_version=1,
        result_guid=result_guid,
        hub_service="gofr-agent",
        expected_result_type="ohlcv_bars",
        expected_schema_id="gofr.ohlcv_bars.v1",
    )


def _describe_request(result_guid: str) -> DescribeResultRequest:
    return DescribeResultRequest(
        protocol_version=1,
        result_guid=result_guid,
        hub_service="gofr-agent",
        expected_result_type="ohlcv_bars",
        expected_schema_id="gofr.ohlcv_bars.v1",
    )


class TestExternalCacheResultStore:
    async def test_atomic_store_and_same_session_get_describe_work(self) -> None:
        clock = _FakeClock(datetime(2026, 5, 16, tzinfo=UTC))
        client = _FakeExternalCacheClient()
        store = ExternalCacheResultStore(_config(), clock=clock, client=client)

        descriptor = await store.store(_scope("session-a"), _store_request())
        fetched = await store.get(_scope("session-a"), _get_request(descriptor.result_guid))
        described = await store.describe(
            _scope("session-a"),
            _describe_request(descriptor.result_guid),
        )

        assert fetched.payload == [{"date": "2026-05-16", "close": 100.0}]
        assert described.metadata.result_guid == descriptor.result_guid

    async def test_cross_session_lookup_returns_unknown_result(self) -> None:
        client = _FakeExternalCacheClient()
        store = ExternalCacheResultStore(_config(), client=client)

        descriptor = await store.store(_scope("session-a"), _store_request())

        with pytest.raises(HubError) as exc_info:
            await store.get(_scope("session-b"), _get_request(descriptor.result_guid))

        assert exc_info.value.code == HUB_UNKNOWN_RESULT

    async def test_expired_result_returns_expired_result(self) -> None:
        clock = _FakeClock(datetime(2026, 5, 16, tzinfo=UTC))
        client = _FakeExternalCacheClient()
        store = ExternalCacheResultStore(
            _config(hub_default_ttl_seconds=1),
            clock=clock,
            client=client,
        )

        descriptor = await store.store(
            _scope("session-a"),
            _store_request(ttl_seconds=1),
        )
        clock.advance(2)

        with pytest.raises(HubError) as exc_info:
            await store.get(_scope("session-a"), _get_request(descriptor.result_guid))

        assert exc_info.value.code == HUB_EXPIRED_RESULT

    async def test_atomic_store_failure_leaves_no_keys(self) -> None:
        client = _FakeExternalCacheClient()
        client.failure_counts["atomic_store_record"] = 2
        store = ExternalCacheResultStore(_config(hub_cache_max_attempts=2), client=client)

        with pytest.raises(HubError) as exc_info:
            await store.store(_scope("session-a"), _store_request())

        assert exc_info.value.code == HUB_STORE_UNAVAILABLE
        assert client.meta == {}
        assert client.payload == {}
        assert all(not members for members in client.indices.values())

    async def test_stale_payload_cleanup_returns_unknown_result(self) -> None:
        client = _FakeExternalCacheClient()
        store = ExternalCacheResultStore(_config(), client=client)
        descriptor = await store.store(_scope("session-a"), _store_request())

        payload_key = next(iter(client.payload))
        del client.payload[payload_key]

        with pytest.raises(HubError) as exc_info:
            await store.get(_scope("session-a"), _get_request(descriptor.result_guid))

        assert exc_info.value.code == HUB_UNKNOWN_RESULT
        assert descriptor.result_guid not in next(iter(client.indices.values()))
        assert client.meta == {}
        assert client.payload == {}

    async def test_capacity_and_oversized_payload_fail_closed(self) -> None:
        client = _FakeExternalCacheClient()
        store = ExternalCacheResultStore(_config(hub_max_results=1), client=client)

        await store.store(_scope("session-a"), _store_request())
        with pytest.raises(HubError) as exc_info:
            await store.store(_scope("session-a"), _store_request())
        assert exc_info.value.code == HUB_CAPACITY_EXCEEDED

        oversized_store = ExternalCacheResultStore(
            _config(hub_max_payload_bytes=4),
            client=_FakeExternalCacheClient(),
        )
        with pytest.raises(HubError) as exc_info:
            await oversized_store.store(_scope("session-a"), _store_request())
        assert exc_info.value.code == HUB_OVERSIZED_RESULT

    async def test_retry_budget_exhaustion_returns_store_unavailable(self) -> None:
        client = _FakeExternalCacheClient()
        store = ExternalCacheResultStore(
            _config(hub_cache_max_attempts=2, hub_cache_retry_backoff_seconds=0),
            client=client,
        )
        descriptor = await store.store(_scope("session-a"), _store_request())
        client.failure_counts["read_record"] = 2

        with pytest.raises(HubError) as exc_info:
            await store.get(_scope("session-a"), _get_request(descriptor.result_guid))

        assert exc_info.value.code == HUB_STORE_UNAVAILABLE

    async def test_stop_suppresses_cache_unavailable_cleanup_errors(self) -> None:
        client = _FakeExternalCacheClient()
        client.failure_counts["stop"] = 1
        store = ExternalCacheResultStore(_config(), client=client)

        await store.stop()

    async def test_keys_include_session_namespace_not_raw_session_id(self) -> None:
        client = _FakeExternalCacheClient()
        store = ExternalCacheResultStore(_config(), client=client)
        scope = _scope("opaque-session-namespace", session_id="raw-user-session")

        await store.store(scope, _store_request())

        all_keys = [
            *client.meta.keys(),
            *client.payload.keys(),
            *client.indices.keys(),
        ]
        assert all("opaque-session-namespace" in key for key in all_keys)
        assert all("raw-user-session" not in key for key in all_keys)
