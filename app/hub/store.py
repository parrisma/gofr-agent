"""Process-local result store for the MCP results hub."""

from __future__ import annotations

import asyncio
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.config import GofrAgentConfig
from app.hub.clock import Clock, SystemClock
from app.hub.errors import (
    HUB_CAPACITY_EXCEEDED,
    HUB_EXPIRED_RESULT,
    HUB_INVALID_PROTOCOL_VERSION,
    HUB_MALFORMED_REQUEST,
    HUB_OVERSIZED_RESULT,
    HUB_SCHEMA_MISMATCH,
    HUB_UNKNOWN_RESULT,
    raise_hub_error,
)
from app.hub.models import (
    DEFAULT_HUB_SERVICE,
    MAX_RESULT_SUMMARY_CHARS,
    MAX_SOURCE_ARGS_BYTES,
    DescribeResultRequest,
    DescribeResultResponse,
    GetResultRequest,
    GetResultResponse,
    ResultDescriptor,
    ResultMetadata,
    StoreResultRequest,
    payload_size_bytes,
)


@dataclass
class StoredResult:
    payload: Any
    metadata: ResultMetadata
    expires_at: datetime


class ResultStore:
    """In-memory bounded store for hub result payloads."""

    def __init__(self, config: GofrAgentConfig, clock: Clock | None = None) -> None:
        self._config = config
        self._results: dict[str, StoredResult] = {}
        self._lock = asyncio.Lock()
        self._clock = clock or SystemClock()

    async def store(self, request: StoreResultRequest) -> ResultDescriptor:
        if request.protocol_version != self._config.hub_protocol_version:
            raise_hub_error(
                HUB_INVALID_PROTOCOL_VERSION,
                f"Expected protocol_version {self._config.hub_protocol_version}",
            )

        requested_ttl = (
            request.ttl_seconds
            if request.ttl_seconds is not None
            else self._config.hub_default_ttl_seconds
        )
        if requested_ttl <= 0:
            raise_hub_error(HUB_MALFORMED_REQUEST, "ttl_seconds must be positive")
        ttl_seconds = min(requested_ttl, self._config.hub_default_ttl_seconds)

        if request.summary is not None and len(request.summary) > MAX_RESULT_SUMMARY_CHARS:
            raise_hub_error(
                HUB_OVERSIZED_RESULT,
                f"summary exceeds max_result_summary_chars ({MAX_RESULT_SUMMARY_CHARS})",
            )

        source_args = request.source_args
        if source_args is not None:
            try:
                source_args = json.loads(
                    json.dumps(source_args, sort_keys=True, separators=(",", ":"))
                )
                source_args_bytes = payload_size_bytes(source_args)
            except TypeError:
                raise_hub_error(
                    HUB_MALFORMED_REQUEST,
                    "source_args must be JSON-serialisable",
                )
            if source_args_bytes > MAX_SOURCE_ARGS_BYTES:
                raise_hub_error(
                    HUB_OVERSIZED_RESULT,
                    f"source_args exceeds max_source_args_bytes ({MAX_SOURCE_ARGS_BYTES})",
                )

        try:
            payload = json.loads(
                json.dumps(request.payload, sort_keys=True, separators=(",", ":"))
            )
            payload_bytes = payload_size_bytes(request.payload)
        except TypeError:
            raise_hub_error(HUB_MALFORMED_REQUEST, "payload must be JSON-serialisable")
        if payload_bytes > self._config.hub_max_payload_bytes:
            raise_hub_error(
                HUB_OVERSIZED_RESULT,
                f"payload exceeds hub_max_payload_bytes ({self._config.hub_max_payload_bytes})",
            )

        created_at = self._clock.utcnow()
        expires_at = created_at + timedelta(seconds=ttl_seconds)
        metadata = ResultMetadata(
            result_guid=secrets.token_urlsafe(32),
            result_type=request.result_type,
            schema_id=request.schema_id,
            producer_service=request.producer_service,
            producer_tool=request.producer_tool,
            created_at=created_at.isoformat(),
            expires_at=expires_at.isoformat(),
            summary=request.summary,
            source_args=source_args,
            payload_bytes=payload_bytes,
        )

        async with self._lock:
            self._prune_expired(created_at)
            if len(self._results) >= self._config.hub_max_results:
                raise_hub_error(
                    HUB_CAPACITY_EXCEEDED,
                    f"hub store is at capacity ({self._config.hub_max_results})",
                )

            self._results[metadata.result_guid] = StoredResult(
                payload=payload,
                metadata=metadata,
                expires_at=expires_at,
            )
            return self._descriptor_for(metadata)

    async def get(self, request: GetResultRequest) -> GetResultResponse:
        metadata, payload = await self._get_record(
            request,
            expected_result_type=request.expected_result_type,
            expected_schema_id=request.expected_schema_id,
        )
        return GetResultResponse(payload=payload, metadata=metadata)

    async def describe(self, request: DescribeResultRequest) -> DescribeResultResponse:
        metadata, _ = await self._get_record(
            request,
            expected_result_type=request.expected_result_type,
            expected_schema_id=request.expected_schema_id,
        )
        return DescribeResultResponse(metadata=metadata)

    async def _get_record(
        self,
        request: GetResultRequest | DescribeResultRequest,
        *,
        expected_result_type: str | None,
        expected_schema_id: str | None,
    ) -> tuple[ResultMetadata, Any]:
        self._validate_lookup_request(request)
        now = self._clock.utcnow()

        async with self._lock:
            record = self._results.get(request.result_guid)
            if record is None:
                raise_hub_error(
                    HUB_UNKNOWN_RESULT,
                    f"Unknown result_guid: {request.result_guid}",
                )

            if record.expires_at <= now:
                del self._results[request.result_guid]
                raise_hub_error(
                    HUB_EXPIRED_RESULT,
                    f"Expired result_guid: {request.result_guid}",
                )

            self._validate_expectations(
                record.metadata,
                expected_result_type=expected_result_type,
                expected_schema_id=expected_schema_id,
            )
            return record.metadata.model_copy(deep=True), json.loads(
                json.dumps(record.payload, sort_keys=True, separators=(",", ":"))
            )

    def _validate_lookup_request(
        self,
        request: GetResultRequest | DescribeResultRequest,
    ) -> None:
        if request.protocol_version != self._config.hub_protocol_version:
            raise_hub_error(
                HUB_INVALID_PROTOCOL_VERSION,
                f"Expected protocol_version {self._config.hub_protocol_version}",
            )
        if request.hub_service != DEFAULT_HUB_SERVICE:
            raise_hub_error(
                HUB_MALFORMED_REQUEST,
                f"hub_service must be {DEFAULT_HUB_SERVICE}",
            )

    def _validate_expectations(
        self,
        metadata: ResultMetadata,
        *,
        expected_result_type: str | None,
        expected_schema_id: str | None,
    ) -> None:
        if (
            expected_result_type is not None
            and expected_result_type != metadata.result_type
        ):
            raise_hub_error(
                HUB_SCHEMA_MISMATCH,
                (
                    "expected_result_type does not match stored result_type: "
                    f"{expected_result_type} != {metadata.result_type}"
                ),
            )
        if expected_schema_id is not None and expected_schema_id != metadata.schema_id:
            raise_hub_error(
                HUB_SCHEMA_MISMATCH,
                (
                    "expected_schema_id does not match stored schema_id: "
                    f"{expected_schema_id} != {metadata.schema_id}"
                ),
            )

    def _descriptor_for(self, metadata: ResultMetadata) -> ResultDescriptor:
        return ResultDescriptor(
            result_guid=metadata.result_guid,
            hub_service=DEFAULT_HUB_SERVICE,
            result_type=metadata.result_type,
            schema_id=metadata.schema_id,
            producer_service=metadata.producer_service,
            producer_tool=metadata.producer_tool,
            created_at=metadata.created_at,
            expires_at=metadata.expires_at,
            summary=metadata.summary,
            source_args=metadata.source_args,
            payload_bytes=metadata.payload_bytes,
        )

    def _prune_expired(self, now: datetime) -> None:
        expired = [guid for guid, record in self._results.items() if record.expires_at <= now]
        for guid in expired:
            del self._results[guid]
