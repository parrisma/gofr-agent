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
from app.hub.store_types import HubAccessScope, HubStoreHealth

_LEGACY_SESSION_NAMESPACE = "__legacy__"


@dataclass
class StoredResult:
    payload: Any
    metadata: ResultMetadata
    expires_at: datetime


class ResultStore:
    """In-memory bounded store for hub result payloads."""

    def __init__(self, config: GofrAgentConfig, clock: Clock | None = None) -> None:
        self._config = config
        self._results: dict[str, dict[str, StoredResult]] = {}
        self._lock = asyncio.Lock()
        self._clock = clock or SystemClock()

    async def start(self) -> None:
        """No-op lifecycle hook for interface compatibility."""

    async def stop(self) -> None:
        """No-op lifecycle hook for interface compatibility."""

    async def health(self) -> HubStoreHealth:
        """Return generic health details for the in-memory backend."""
        now = self._clock.utcnow()
        async with self._lock:
            self._prune_expired(now)
            result_count = sum(len(results) for results in self._results.values())
        return HubStoreHealth(
            backend="memory",
            status="healthy",
            reachable=True,
            indexed_result_count=result_count,
        )

    async def store(
        self,
        scope: HubAccessScope | StoreResultRequest,
        request: StoreResultRequest | None = None,
    ) -> ResultDescriptor:
        session_namespace, request = self._coerce_store_call(scope, request)
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
            self._prune_expired(created_at, session_namespace=session_namespace)
            session_results = self._results.setdefault(session_namespace, {})
            if len(session_results) >= self._config.hub_max_results:
                raise_hub_error(
                    HUB_CAPACITY_EXCEEDED,
                    f"hub store is at capacity ({self._config.hub_max_results})",
                )

            session_results[metadata.result_guid] = StoredResult(
                payload=payload,
                metadata=metadata,
                expires_at=expires_at,
            )
            return self._descriptor_for(metadata)

    async def get(
        self,
        scope: HubAccessScope | GetResultRequest,
        request: GetResultRequest | None = None,
    ) -> GetResultResponse:
        session_namespace, request = self._coerce_get_call(scope, request)
        metadata, payload = await self._get_record(
            session_namespace,
            request,
            expected_result_type=request.expected_result_type,
            expected_schema_id=request.expected_schema_id,
        )
        return GetResultResponse(payload=payload, metadata=metadata)

    async def describe(
        self,
        scope: HubAccessScope | DescribeResultRequest,
        request: DescribeResultRequest | None = None,
    ) -> DescribeResultResponse:
        session_namespace, request = self._coerce_describe_call(scope, request)
        metadata, _ = await self._get_record(
            session_namespace,
            request,
            expected_result_type=request.expected_result_type,
            expected_schema_id=request.expected_schema_id,
        )
        return DescribeResultResponse(metadata=metadata)

    @staticmethod
    def _coerce_store_call(
        scope: HubAccessScope | StoreResultRequest,
        request: StoreResultRequest | None,
    ) -> tuple[str, StoreResultRequest]:
        if isinstance(scope, StoreResultRequest):
            if request is not None:
                raise TypeError("request must not be provided twice")
            return _LEGACY_SESSION_NAMESPACE, scope
        if request is None:
            raise TypeError("request is required when scope is provided")
        return scope.session_namespace, request

    @staticmethod
    def _coerce_get_call(
        scope: HubAccessScope | GetResultRequest,
        request: GetResultRequest | None,
    ) -> tuple[str, GetResultRequest]:
        if isinstance(scope, GetResultRequest):
            if request is not None:
                raise TypeError("request must not be provided twice")
            return _LEGACY_SESSION_NAMESPACE, scope
        if request is None:
            raise TypeError("request is required when scope is provided")
        return scope.session_namespace, request

    @staticmethod
    def _coerce_describe_call(
        scope: HubAccessScope | DescribeResultRequest,
        request: DescribeResultRequest | None,
    ) -> tuple[str, DescribeResultRequest]:
        if isinstance(scope, DescribeResultRequest):
            if request is not None:
                raise TypeError("request must not be provided twice")
            return _LEGACY_SESSION_NAMESPACE, scope
        if request is None:
            raise TypeError("request is required when scope is provided")
        return scope.session_namespace, request

    async def _get_record(
        self,
        session_namespace: str,
        request: GetResultRequest | DescribeResultRequest,
        *,
        expected_result_type: str | None,
        expected_schema_id: str | None,
    ) -> tuple[ResultMetadata, Any]:
        self._validate_lookup_request(request)
        now = self._clock.utcnow()

        async with self._lock:
            session_results = self._results.get(session_namespace)
            record = None if session_results is None else session_results.get(request.result_guid)
            if record is None:
                raise_hub_error(
                    HUB_UNKNOWN_RESULT,
                    f"Unknown result_guid: {request.result_guid}",
                )

            assert session_results is not None
            if record.expires_at <= now:
                del session_results[request.result_guid]
                if not session_results:
                    del self._results[session_namespace]
                raise_hub_error(
                    HUB_EXPIRED_RESULT,
                    f"Expired result_guid: {request.result_guid}",
                )

            self._validate_expectations(
                metadata=record.metadata,
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
        *,
        metadata: ResultMetadata,
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

    def _prune_expired(self, now: datetime, *, session_namespace: str | None = None) -> None:
        namespaces = [session_namespace] if session_namespace is not None else list(self._results)
        for namespace in namespaces:
            session_results = self._results.get(namespace)
            if session_results is None:
                continue
            expired = [
                guid
                for guid, record in session_results.items()
                if record.expires_at <= now
            ]
            for guid in expired:
                del session_results[guid]
            if not session_results:
                del self._results[namespace]
