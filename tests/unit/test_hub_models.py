"""Tests for hub protocol models."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.hub.models import (
    DescribeResultRequest,
    DescribeResultResponse,
    GetResultRequest,
    GetResultResponse,
    ResultDescriptor,
    ResultMetadata,
    StoreResultRequest,
    StoreResultResponse,
)


class TestResultDescriptor:
    def test_requires_structural_fields(self) -> None:
        descriptor = ResultDescriptor(
            result_guid="guid-123",
            hub_service="gofr-agent",
        )

        assert descriptor.kind == "gofr.result_ref"
        assert descriptor.version == 1

    def test_accepts_advisory_fields(self) -> None:
        descriptor = ResultDescriptor(
            result_guid="guid-123",
            hub_service="gofr-agent",
            result_type="ohlcv_bars",
            schema_id="gofr.ohlcv_bars.v1",
            producer_service="hub-fixture",
            producer_tool="debug_reentrant_store_result",
            created_at="2026-05-16T00:00:00+00:00",
            expires_at="2026-05-16T00:01:00+00:00",
            summary="two bars",
            source_args={"ticker": "AAPL"},
            payload_bytes=128,
        )

        assert descriptor.result_type == "ohlcv_bars"
        assert descriptor.source_args == {"ticker": "AAPL"}

    def test_invalid_kind_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ResultDescriptor.model_validate(
                {
                    "kind": "wrong.kind",
                    "version": 1,
                    "result_guid": "guid-123",
                    "hub_service": "gofr-agent",
                }
            )

    def test_invalid_version_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ResultDescriptor.model_validate(
                {
                    "kind": "gofr.result_ref",
                    "version": 2,
                    "result_guid": "guid-123",
                    "hub_service": "gofr-agent",
                }
            )

    def test_structural_validation_helper_rejects_bad_descriptor(self) -> None:
        with pytest.raises(ValidationError):
            ResultDescriptor.validate_reference(
                {
                    "kind": "gofr.result_ref",
                    "version": 2,
                    "result_guid": "guid-123",
                    "hub_service": "gofr-agent",
                }
            )

    def test_structural_validation_helper_accepts_json_string(self) -> None:
        descriptor = ResultDescriptor.validate_reference(
            json.dumps(
                {
                    "kind": "gofr.result_ref",
                    "version": 1,
                    "result_guid": "guid-123",
                    "hub_service": "gofr-agent",
                }
            )
        )

        assert descriptor.result_guid == "guid-123"

    def test_serialised_descriptor_never_contains_payload(self) -> None:
        descriptor = ResultDescriptor(result_guid="guid-123", hub_service="gofr-agent")

        assert "payload" not in descriptor.model_dump()
        assert "payload" not in json.loads(descriptor.model_dump_json())


class TestRequestResponseModels:
    def test_store_result_request_requires_required_fields(self) -> None:
        request = StoreResultRequest(
            protocol_version=1,
            producer_service="hub-fixture",
            producer_tool="debug_reentrant_store_result",
            result_type="ohlcv_bars",
            schema_id="gofr.ohlcv_bars.v1",
            payload=[{"close": 100.0}],
        )

        assert request.producer_service == "hub-fixture"

    def test_store_result_request_rejects_missing_payload(self) -> None:
        with pytest.raises(ValidationError):
            StoreResultRequest.model_validate(
                {
                    "protocol_version": 1,
                    "producer_service": "hub-fixture",
                    "producer_tool": "debug_reentrant_store_result",
                    "result_type": "ohlcv_bars",
                    "schema_id": "gofr.ohlcv_bars.v1",
                }
            )

    def test_get_result_request_requires_structural_fields(self) -> None:
        request = GetResultRequest(
            protocol_version=1,
            result_guid="guid-123",
            hub_service="gofr-agent",
        )

        assert request.result_guid == "guid-123"

    def test_describe_result_request_requires_structural_fields(self) -> None:
        request = DescribeResultRequest(
            protocol_version=1,
            result_guid="guid-123",
            hub_service="gofr-agent",
        )

        assert request.hub_service == "gofr-agent"

    def test_result_metadata_contains_authoritative_fields(self) -> None:
        metadata = ResultMetadata(
            result_guid="guid-123",
            result_type="ohlcv_bars",
            schema_id="gofr.ohlcv_bars.v1",
            producer_service="hub-fixture",
            producer_tool="debug_reentrant_store_result",
            created_at="2026-05-16T00:00:00+00:00",
            expires_at="2026-05-16T00:01:00+00:00",
            payload_bytes=128,
            source_args={"ticker": "AAPL"},
        )

        assert metadata.producer_service == "hub-fixture"
        assert metadata.payload_bytes == 128

    def test_store_response_wraps_descriptor(self) -> None:
        response = StoreResultResponse(
            descriptor=ResultDescriptor(result_guid="guid-123", hub_service="gofr-agent")
        )

        payload = json.loads(response.model_dump_json())
        assert payload["descriptor"]["result_guid"] == "guid-123"

    def test_get_response_wraps_payload_and_metadata(self) -> None:
        response = GetResultResponse(
            payload=[{"close": 100.0}],
            metadata=ResultMetadata(
                result_guid="guid-123",
                result_type="ohlcv_bars",
                schema_id="gofr.ohlcv_bars.v1",
                producer_service="hub-fixture",
                producer_tool="debug_reentrant_store_result",
                created_at="2026-05-16T00:00:00+00:00",
                expires_at="2026-05-16T00:01:00+00:00",
                payload_bytes=128,
            ),
        )

        assert response.payload == [{"close": 100.0}]

    def test_describe_response_wraps_metadata_only(self) -> None:
        response = DescribeResultResponse(
            metadata=ResultMetadata(
                result_guid="guid-123",
                result_type="ohlcv_bars",
                schema_id="gofr.ohlcv_bars.v1",
                producer_service="hub-fixture",
                producer_tool="debug_reentrant_store_result",
                created_at="2026-05-16T00:00:00+00:00",
                expires_at="2026-05-16T00:01:00+00:00",
                payload_bytes=128,
            )
        )

        assert response.metadata.result_guid == "guid-123"
