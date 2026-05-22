"""External-cache-backed result store for the MCP results hub."""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any, TypeVar

from pydantic import ValidationError

from app.config import GofrAgentConfig
from app.hub.clock import Clock, SystemClock
from app.hub.errors import (
    HUB_CAPACITY_EXCEEDED,
    HUB_EXPIRED_RESULT,
    HUB_INVALID_PROTOCOL_VERSION,
    HUB_MALFORMED_REQUEST,
    HUB_OVERSIZED_RESULT,
    HUB_SCHEMA_MISMATCH,
    HUB_STORE_UNAVAILABLE,
    HUB_UNKNOWN_RESULT,
    HubError,
    raise_hub_error,
)
from app.hub.external_cache_client import (
    ExternalCacheCapacityExceededError,
    ExternalCacheClient,
    ExternalCacheUnavailableError,
    RedisExternalCacheClient,
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
_T = TypeVar("_T")


class ExternalCacheResultStore:
    """Hub result store backed by an external cache adapter."""

    def __init__(
        self,
        config: GofrAgentConfig,
        *,
        clock: Clock | None = None,
        client: ExternalCacheClient | None = None,
    ) -> None:
        self._config = config
        self._clock = clock or SystemClock()
        self._client = client or RedisExternalCacheClient(config)

    async def start(self) -> None:
        await self._run_cache_op("start", self._client.start)

    async def stop(self) -> None:
        with contextlib.suppress(
            ExternalCacheUnavailableError,
            OSError,
            asyncio.CancelledError,
        ):
            await self._client.stop()

    async def health(self) -> HubStoreHealth:
        try:
            reachable = await self._run_cache_op("health_ping", self._client.ping)
            indexed_result_count = await self._run_cache_op(
                "health_count",
                lambda: self._client.count_indexed_results(
                    key_prefix=self._config.hub_cache_key_prefix
                ),
            )
        except HubError as exc:
            return HubStoreHealth(
                backend="external_cache",
                status="failed",
                reachable=False,
                error=exc.message[:256],
            )

        return HubStoreHealth(
            backend="external_cache",
            status="healthy" if reachable else "failed",
            reachable=reachable,
            indexed_result_count=indexed_result_count,
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
                raise_hub_error(HUB_MALFORMED_REQUEST, "source_args must be JSON-serialisable")
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
        meta_json = metadata.model_dump_json()
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        meta_key = self._meta_key(session_namespace, metadata.result_guid)
        payload_key = self._payload_key(session_namespace, metadata.result_guid)
        index_key = self._index_key(session_namespace)

        try:
            await self._run_cache_op(
                "store",
                lambda: self._client.atomic_store_record(
                    meta_key=meta_key,
                    payload_key=payload_key,
                    index_key=index_key,
                    result_guid=metadata.result_guid,
                    meta_json=meta_json,
                    payload_json=payload_json,
                    expires_at_timestamp=expires_at.timestamp(),
                    now_timestamp=created_at.timestamp(),
                    ttl_seconds=ttl_seconds,
                    max_results=self._config.hub_max_results,
                ),
            )
        except ExternalCacheCapacityExceededError:
            raise_hub_error(
                HUB_CAPACITY_EXCEEDED,
                f"hub store is at capacity ({self._config.hub_max_results})",
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
        expired_guids = await self._prune_expired(session_namespace, now)
        if request.result_guid in expired_guids:
            raise_hub_error(HUB_EXPIRED_RESULT, f"Expired result_guid: {request.result_guid}")

        meta_key = self._meta_key(session_namespace, request.result_guid)
        payload_key = self._payload_key(session_namespace, request.result_guid)
        meta_json, payload_json = await self._run_cache_op(
            "read_record",
            lambda: self._client.read_record(meta_key=meta_key, payload_key=payload_key),
        )

        if meta_json is None and payload_json is None:
            raise_hub_error(HUB_UNKNOWN_RESULT, f"Unknown result_guid: {request.result_guid}")
        if meta_json is None or payload_json is None:
            await self._cleanup_inconsistent_record(session_namespace, request.result_guid)
            raise_hub_error(HUB_UNKNOWN_RESULT, f"Unknown result_guid: {request.result_guid}")

        try:
            metadata = ResultMetadata.model_validate_json(meta_json)
            payload = json.loads(payload_json)
        except (ValidationError, json.JSONDecodeError):
            await self._cleanup_inconsistent_record(session_namespace, request.result_guid)
            raise_hub_error(HUB_UNKNOWN_RESULT, f"Unknown result_guid: {request.result_guid}")

        expires_at = datetime.fromisoformat(metadata.expires_at)
        if expires_at <= now:
            with contextlib.suppress(HubError):
                await self._cleanup_record(session_namespace, request.result_guid)
            raise_hub_error(HUB_EXPIRED_RESULT, f"Expired result_guid: {request.result_guid}")

        self._validate_expectations(
            metadata=metadata,
            expected_result_type=expected_result_type,
            expected_schema_id=expected_schema_id,
        )
        return metadata.model_copy(deep=True), payload

    async def _prune_expired(self, session_namespace: str, now: datetime) -> tuple[str, ...]:
        expired_guids = await self._run_cache_op(
            "prune_expired",
            lambda: self._client.prune_expired(
                index_key=self._index_key(session_namespace),
                before_timestamp=now.timestamp(),
            ),
        )
        if not expired_guids:
            return ()
        await self._delete_record_keys(session_namespace, expired_guids)
        return expired_guids

    async def _cleanup_inconsistent_record(
        self,
        session_namespace: str,
        result_guid: str,
    ) -> None:
        with contextlib.suppress(HubError):
            await self._cleanup_record(session_namespace, result_guid)

    async def _cleanup_record(self, session_namespace: str, result_guid: str) -> None:
        await self._run_cache_op(
            "remove_index_member",
            lambda: self._client.remove_index_member(
                index_key=self._index_key(session_namespace),
                result_guid=result_guid,
            ),
        )
        await self._delete_record_keys(session_namespace, (result_guid,))

    async def _delete_record_keys(
        self,
        session_namespace: str,
        result_guids: tuple[str, ...],
    ) -> None:
        keys: list[str] = []
        for result_guid in result_guids:
            keys.append(self._meta_key(session_namespace, result_guid))
            keys.append(self._payload_key(session_namespace, result_guid))
        await self._run_cache_op("delete_keys", lambda: self._client.delete_keys(*keys))

    async def _run_cache_op(
        self,
        operation: str,
        func: Callable[[], Awaitable[_T]],
    ) -> _T:
        attempts = max(self._config.hub_cache_max_attempts, 1)
        started_at = self._clock.monotonic()
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                return await asyncio.wait_for(
                    func(),
                    timeout=self._config.hub_cache_operation_timeout_seconds,
                )
            except ExternalCacheCapacityExceededError:
                raise
            except (ExternalCacheUnavailableError, TimeoutError, OSError) as exc:
                last_error = exc
                elapsed = self._clock.monotonic() - started_at
                if attempt >= attempts or elapsed >= self._config.hub_cache_request_budget_seconds:
                    break
                if self._config.hub_cache_retry_backoff_seconds > 0:
                    remaining_budget = self._config.hub_cache_request_budget_seconds - elapsed
                    if remaining_budget <= 0:
                        break
                    await asyncio.sleep(
                        min(self._config.hub_cache_retry_backoff_seconds, remaining_budget)
                    )

        message = f"external cache unavailable during {operation}"
        if last_error is not None and str(last_error):
            message = f"{message}: {last_error}"
        raise_hub_error(HUB_STORE_UNAVAILABLE, message)

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
            raise_hub_error(HUB_MALFORMED_REQUEST, f"hub_service must be {DEFAULT_HUB_SERVICE}")

    def _validate_expectations(
        self,
        *,
        metadata: ResultMetadata,
        expected_result_type: str | None,
        expected_schema_id: str | None,
    ) -> None:
        if expected_result_type is not None and expected_result_type != metadata.result_type:
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

    def _index_key(self, session_namespace: str) -> str:
        return f"{self._config.hub_cache_key_prefix}:session:{session_namespace}:results"

    def _meta_key(self, session_namespace: str, result_guid: str) -> str:
        return (
            f"{self._config.hub_cache_key_prefix}:session:{session_namespace}:"
            f"result:{result_guid}:meta"
        )

    def _payload_key(self, session_namespace: str, result_guid: str) -> str:
        return (
            f"{self._config.hub_cache_key_prefix}:session:{session_namespace}:"
            f"result:{result_guid}:payload"
        )
