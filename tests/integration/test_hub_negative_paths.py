"""Integration tests for hub negative paths not covered by producer/consumer suites."""

from __future__ import annotations

import pytest

from tests.integration.test_analytics_hub_integration import (
    _CONSUMER_CALLBACK_TOKEN,
    _PRODUCER_CALLBACK_TOKEN,
    _call_tool,
    _get_descriptor,
    _start_stack,
)


@pytest.mark.asyncio
class TestHubNegativePaths:
    async def test_get_result_unknown_guid_returns_unknown_result(self) -> None:
        stack = await _start_stack()

        try:
            is_error, raw = await _call_tool(
                stack.local_hub_url,
                "_get_result",
                {
                    "protocol_version": 1,
                    "result_guid": "missing-guid",
                    "hub_service": "gofr-agent",
                    "expected_result_type": "ohlcv_bars",
                    "expected_schema_id": "gofr.ohlcv_bars.v1",
                },
                headers={"Authorization": f"Bearer {_CONSUMER_CALLBACK_TOKEN}"},
            )

            assert is_error is True
            assert "hub.unknown_result" in raw
        finally:
            await stack.shutdown()

    async def test_store_result_rejects_mismatched_producer_service(self) -> None:
        stack = await _start_stack()

        try:
            is_error, raw = await _call_tool(
                stack.local_hub_url,
                "_store_result",
                {
                    "protocol_version": 1,
                    "producer_service": "analytics",
                    "producer_tool": "simple_return",
                    "result_type": "ohlcv_bars",
                    "schema_id": "gofr.ohlcv_bars.v1",
                    "payload": [{"date": "2026-05-13", "close": 182.917}],
                    "summary": "bad producer",
                },
                headers={"Authorization": f"Bearer {_PRODUCER_CALLBACK_TOKEN}"},
            )

            assert is_error is True
            assert "hub.unregistered_service" in raw
        finally:
            await stack.shutdown()

    async def test_store_result_rejects_disallowed_result_type(self) -> None:
        stack = await _start_stack()

        try:
            is_error, raw = await _call_tool(
                stack.local_hub_url,
                "_store_result",
                {
                    "protocol_version": 1,
                    "producer_service": "instruments",
                    "producer_tool": "get_ohlcv_history",
                    "result_type": "unexpected_type",
                    "schema_id": "gofr.ohlcv_bars.v1",
                    "payload": [{"date": "2026-05-13", "close": 182.917}],
                    "summary": "bad result type",
                },
                headers={"Authorization": f"Bearer {_PRODUCER_CALLBACK_TOKEN}"},
            )

            assert is_error is True
            assert "hub.result_type_not_allowed" in raw
        finally:
            await stack.shutdown()

    async def test_get_result_rejects_disallowed_expected_result_type(self) -> None:
        stack = await _start_stack()

        try:
            descriptor = await _get_descriptor(stack)
            is_error, raw = await _call_tool(
                stack.local_hub_url,
                "_get_result",
                {
                    "protocol_version": 1,
                    "result_guid": descriptor["result_guid"],
                    "hub_service": descriptor["hub_service"],
                    "expected_result_type": "unexpected_type",
                    "expected_schema_id": "gofr.ohlcv_bars.v1",
                },
                headers={"Authorization": f"Bearer {_CONSUMER_CALLBACK_TOKEN}"},
            )

            assert is_error is True
            assert "hub.result_type_not_allowed" in raw
        finally:
            await stack.shutdown()
