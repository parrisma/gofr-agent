"""Hub protocol models and helpers for result handoff."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RESULT_DESCRIPTOR_KIND = "gofr.result_ref"
RESULT_DESCRIPTOR_VERSION = 1
DEFAULT_HUB_SERVICE = "gofr-agent"
REGISTER_RESULTS_HUB_TOOL = "_register_results_hub"
STORE_RESULT_TOOL = "_store_result"
GET_RESULT_TOOL = "_get_result"
DESCRIBE_RESULT_TOOL = "_describe_result"
MAX_RESULT_SUMMARY_CHARS = 1024
MAX_SOURCE_ARGS_BYTES = 4096


class HubModel(BaseModel):
    """Base model for hub protocol payloads."""

    model_config = ConfigDict(extra="forbid")


class ResultDescriptor(HubModel):
    """Model-safe reference to a payload stored in the hub."""

    kind: Literal["gofr.result_ref"] = RESULT_DESCRIPTOR_KIND
    version: Literal[1] = RESULT_DESCRIPTOR_VERSION
    result_guid: str
    hub_service: str = DEFAULT_HUB_SERVICE
    result_type: str | None = None
    schema_id: str | None = None
    producer_service: str | None = None
    producer_tool: str | None = None
    created_at: str | None = None
    expires_at: str | None = None
    summary: str | None = None
    source_args: dict[str, Any] | None = None
    payload_bytes: int | None = None

    @classmethod
    def validate_reference(cls, value: object) -> ResultDescriptor:
        """Validate an opaque descriptor-like value."""

        if isinstance(value, str):
            value = json.loads(value)

        return cls.model_validate(value)


class ResultMetadata(HubModel):
    """Authoritative metadata returned by the hub for a stored result."""

    result_guid: str
    result_type: str
    schema_id: str
    producer_service: str
    producer_tool: str
    created_at: str
    expires_at: str
    payload_bytes: int
    summary: str | None = None
    source_args: dict[str, Any] | None = None


class StoreResultRequest(HubModel):
    """Request payload for `_store_result`."""

    protocol_version: int = Field(ge=1)
    producer_service: str
    producer_tool: str
    result_type: str
    schema_id: str
    payload: Any
    summary: str | None = None
    source_args: dict[str, Any] | None = None
    ttl_seconds: int | None = None


class ResultLookupRequest(HubModel):
    """Common request shape for get/describe calls."""

    protocol_version: int = Field(ge=1)
    result_guid: str
    hub_service: str
    expected_result_type: str | None = None
    expected_schema_id: str | None = None


class GetResultRequest(ResultLookupRequest):
    """Request payload for `_get_result`."""


class DescribeResultRequest(ResultLookupRequest):
    """Request payload for `_describe_result`."""


class StoreResultResponse(HubModel):
    """Response payload for `_store_result`."""

    descriptor: ResultDescriptor


class GetResultResponse(HubModel):
    """Response payload for `_get_result`."""

    payload: Any
    metadata: ResultMetadata


class DescribeResultResponse(HubModel):
    """Response payload for `_describe_result`."""

    metadata: ResultMetadata


class RegisterResultsHubRequest(HubModel):
    """Request payload for `_register_results_hub`."""

    protocol_version: int = Field(ge=1)
    hub_service: str = DEFAULT_HUB_SERVICE
    hub_url: str
    store_tool: str = STORE_RESULT_TOOL
    fetch_tool: str = GET_RESULT_TOOL
    describe_tool: str = DESCRIBE_RESULT_TOOL
    default_ttl_seconds: int
    max_payload_bytes: int
    descriptor_kind: Literal["gofr.result_ref"] = RESULT_DESCRIPTOR_KIND


class RegisterResultsHubResponse(HubModel):
    """Response payload for `_register_results_hub`."""

    accepted: bool
    protocol_version: int = Field(ge=1)
    can_publish: bool
    can_consume: bool
    result_types: list[str]
    notes: str | None = None


def payload_size_bytes(payload: Any) -> int:
    """Return the canonical serialized payload size in bytes."""
    return len(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
