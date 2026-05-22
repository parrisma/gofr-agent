"""Tests for the in-memory hub result store."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.config import GofrAgentConfig
from app.hub.errors import (
    HUB_CAPACITY_EXCEEDED,
    HUB_EXPIRED_RESULT,
    HUB_MALFORMED_REQUEST,
    HUB_OVERSIZED_RESULT,
    HUB_SCHEMA_MISMATCH,
    HUB_UNKNOWN_RESULT,
    HubError,
)
from app.hub.models import (
    MAX_RESULT_SUMMARY_CHARS,
    MAX_SOURCE_ARGS_BYTES,
    DescribeResultRequest,
    GetResultRequest,
    StoreResultRequest,
)
from app.hub.store import ResultStore
from app.hub.store_types import HubAccessScope


class _FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def utcnow(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._now.timestamp()

    def advance(self, seconds: int) -> None:
        self._now += timedelta(seconds=seconds)


def _config(**overrides: int) -> GofrAgentConfig:
    defaults = {
        "hub_default_ttl_seconds": 60,
        "hub_max_payload_bytes": 512,
        "hub_max_results": 4,
    }
    defaults.update(overrides)
    return GofrAgentConfig(hub_enabled=False, **defaults)


def _request(**overrides) -> StoreResultRequest:  # type: ignore[no-untyped-def]
    payload = [{"date": "2026-05-16", "close": 100.0}]
    defaults = {
        "protocol_version": 1,
        "producer_service": "hub-fixture",
        "producer_tool": "debug_reentrant_store_result",
        "result_type": "ohlcv_bars",
        "schema_id": "gofr.ohlcv_bars.v1",
        "payload": payload,
        "summary": "one bar",
        "source_args": {"ticker": "AAPL"},
        "ttl_seconds": 30,
    }
    defaults.update(overrides)
    return StoreResultRequest(**defaults)


def _scope(session_namespace: str = "session-a") -> HubAccessScope:
    return HubAccessScope(
        session_namespace=session_namespace,
        principal_service="hub-fixture",
        allowed_operations=("store", "get", "describe"),
        allowed_result_types=("ohlcv_bars",),
    )


class TestResultStore:
    async def test_store_returns_urlsafe_guid_descriptor(self) -> None:
        store = ResultStore(
            _config(),
            clock=_FakeClock(datetime(2026, 5, 16, tzinfo=UTC)),
        )

        descriptor = await store.store(_request())

        assert len(descriptor.result_guid) == 43

    async def test_store_generates_unique_guids(self) -> None:
        store = ResultStore(
            _config(hub_max_results=64),
            clock=_FakeClock(datetime(2026, 5, 16, tzinfo=UTC)),
        )

        descriptors = [await store.store(_request(summary=f"bar-{index}")) for index in range(20)]

        assert len({descriptor.result_guid for descriptor in descriptors}) == 20

    async def test_get_returns_payload_and_authoritative_metadata(self) -> None:
        store = ResultStore(
            _config(),
            clock=_FakeClock(datetime(2026, 5, 16, tzinfo=UTC)),
        )
        descriptor = await store.store(_request())

        response = await store.get(
            GetResultRequest(
                protocol_version=1,
                result_guid=descriptor.result_guid,
                hub_service="gofr-agent",
                expected_result_type="ohlcv_bars",
                expected_schema_id="gofr.ohlcv_bars.v1",
            )
        )

        assert response.payload == [{"date": "2026-05-16", "close": 100.0}]
        assert response.metadata.result_guid == descriptor.result_guid

    async def test_get_unknown_guid_raises(self) -> None:
        store = ResultStore(
            _config(),
            clock=_FakeClock(datetime(2026, 5, 16, tzinfo=UTC)),
        )

        with pytest.raises(HubError) as exc_info:
            await store.get(
                GetResultRequest(
                    protocol_version=1,
                    result_guid="missing",
                    hub_service="gofr-agent",
                )
            )
        assert exc_info.value.code == HUB_UNKNOWN_RESULT

    async def test_get_after_expiry_raises(self) -> None:
        clock = _FakeClock(datetime(2026, 5, 16, tzinfo=UTC))
        store = ResultStore(_config(), clock=clock)
        descriptor = await store.store(_request(ttl_seconds=5))
        clock.advance(6)

        with pytest.raises(HubError) as exc_info:
            await store.get(
                GetResultRequest(
                    protocol_version=1,
                    result_guid=descriptor.result_guid,
                    hub_service="gofr-agent",
                )
            )
        assert exc_info.value.code == HUB_EXPIRED_RESULT

    async def test_oversized_payload_is_rejected(self) -> None:
        store = ResultStore(
            _config(hub_max_payload_bytes=10),
            clock=_FakeClock(datetime(2026, 5, 16, tzinfo=UTC)),
        )

        with pytest.raises(HubError) as exc_info:
            await store.store(_request())
        assert exc_info.value.code == HUB_OVERSIZED_RESULT

    async def test_capacity_exceeded_is_rejected(self) -> None:
        store = ResultStore(
            _config(hub_max_results=1),
            clock=_FakeClock(datetime(2026, 5, 16, tzinfo=UTC)),
        )
        await store.store(_request(summary="one"))

        with pytest.raises(HubError) as exc_info:
            await store.store(_request(summary="two"))
        assert exc_info.value.code == HUB_CAPACITY_EXCEEDED

    async def test_oversized_summary_is_rejected(self) -> None:
        store = ResultStore(
            _config(),
            clock=_FakeClock(datetime(2026, 5, 16, tzinfo=UTC)),
        )

        with pytest.raises(HubError) as exc_info:
            await store.store(_request(summary="x" * (MAX_RESULT_SUMMARY_CHARS + 1)))
        assert exc_info.value.code == HUB_OVERSIZED_RESULT

    async def test_oversized_source_args_is_rejected(self) -> None:
        store = ResultStore(
            _config(),
            clock=_FakeClock(datetime(2026, 5, 16, tzinfo=UTC)),
        )

        with pytest.raises(HubError) as exc_info:
            await store.store(
                _request(source_args={"ticker": "AAPL", "blob": "x" * MAX_SOURCE_ARGS_BYTES})
            )
        assert exc_info.value.code == HUB_OVERSIZED_RESULT

    async def test_requested_ttl_is_capped_by_config(self) -> None:
        store = ResultStore(
            _config(hub_default_ttl_seconds=15),
            clock=_FakeClock(datetime(2026, 5, 16, tzinfo=UTC)),
        )

        descriptor = await store.store(_request(ttl_seconds=30))

        assert descriptor.expires_at == "2026-05-16T00:00:15+00:00"

    async def test_non_positive_ttl_is_rejected(self) -> None:
        store = ResultStore(
            _config(),
            clock=_FakeClock(datetime(2026, 5, 16, tzinfo=UTC)),
        )

        with pytest.raises(HubError) as exc_info:
            await store.store(_request(ttl_seconds=0))
        assert exc_info.value.code == HUB_MALFORMED_REQUEST

    async def test_authoritative_metadata_not_affected_by_descriptor_mutation(self) -> None:
        store = ResultStore(
            _config(),
            clock=_FakeClock(datetime(2026, 5, 16, tzinfo=UTC)),
        )
        descriptor = await store.store(_request(summary="original-summary"))
        descriptor.summary = "tampered-summary"

        response = await store.describe(
            DescribeResultRequest(
                protocol_version=1,
                result_guid=descriptor.result_guid,
                hub_service="gofr-agent",
            )
        )

        assert response.metadata.summary == "original-summary"

    async def test_expected_type_and_schema_mismatch_raise(self) -> None:
        store = ResultStore(
            _config(),
            clock=_FakeClock(datetime(2026, 5, 16, tzinfo=UTC)),
        )
        descriptor = await store.store(_request())

        with pytest.raises(HubError) as type_exc:
            await store.get(
                GetResultRequest(
                    protocol_version=1,
                    result_guid=descriptor.result_guid,
                    hub_service="gofr-agent",
                    expected_result_type="positions",
                )
            )
        assert type_exc.value.code == HUB_SCHEMA_MISMATCH

        with pytest.raises(HubError) as schema_exc:
            await store.describe(
                DescribeResultRequest(
                    protocol_version=1,
                    result_guid=descriptor.result_guid,
                    hub_service="gofr-agent",
                    expected_schema_id="wrong.schema.v1",
                )
            )
        assert schema_exc.value.code == HUB_SCHEMA_MISMATCH

    async def test_explicit_scope_store_get_and_describe_work(self) -> None:
        store = ResultStore(
            _config(),
            clock=_FakeClock(datetime(2026, 5, 16, tzinfo=UTC)),
        )
        scope = _scope("session-a")

        descriptor = await store.store(scope, _request())
        get_response = await store.get(
            scope,
            GetResultRequest(
                protocol_version=1,
                result_guid=descriptor.result_guid,
                hub_service="gofr-agent",
            ),
        )
        describe_response = await store.describe(
            scope,
            DescribeResultRequest(
                protocol_version=1,
                result_guid=descriptor.result_guid,
                hub_service="gofr-agent",
            ),
        )

        assert get_response.payload == [{"date": "2026-05-16", "close": 100.0}]
        assert describe_response.metadata.result_guid == descriptor.result_guid

    async def test_cross_session_lookup_returns_unknown_result(self) -> None:
        store = ResultStore(
            _config(),
            clock=_FakeClock(datetime(2026, 5, 16, tzinfo=UTC)),
        )
        descriptor = await store.store(_scope("session-a"), _request())

        with pytest.raises(HubError) as exc_info:
            await store.get(
                _scope("session-b"),
                GetResultRequest(
                    protocol_version=1,
                    result_guid=descriptor.result_guid,
                    hub_service="gofr-agent",
                ),
            )

        assert exc_info.value.code == HUB_UNKNOWN_RESULT

    async def test_capacity_is_enforced_per_session(self) -> None:
        store = ResultStore(
            _config(hub_max_results=1),
            clock=_FakeClock(datetime(2026, 5, 16, tzinfo=UTC)),
        )

        await store.store(_scope("session-a"), _request(summary="one"))
        await store.store(_scope("session-b"), _request(summary="two"))

        with pytest.raises(HubError) as exc_info:
            await store.store(_scope("session-a"), _request(summary="three"))

        assert exc_info.value.code == HUB_CAPACITY_EXCEEDED

    async def test_descriptor_remains_session_neutral_with_explicit_scope(self) -> None:
        store = ResultStore(
            _config(),
            clock=_FakeClock(datetime(2026, 5, 16, tzinfo=UTC)),
        )

        descriptor = await store.store(_scope("session-a"), _request())
        payload = descriptor.model_dump(exclude_none=True)

        assert "session_id" not in payload
        assert "session_namespace" not in payload
