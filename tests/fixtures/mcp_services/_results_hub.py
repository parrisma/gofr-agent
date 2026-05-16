"""Shared results-hub helpers for test fixture MCP services."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.hub.models import GetResultResponse, ResultDescriptor

GOFR_FIXTURES_HUB_CALLBACK_TOKEN = "GOFR_FIXTURES_HUB_CALLBACK_TOKEN"
_HUB_CALLBACK_TIMEOUT = httpx.Timeout(10.0, connect=2.0)


@dataclass
class ResultsHubState:
    protocol_version: int = 1
    hub_service: str | None = None
    hub_url: str | None = None
    callback_token: str | None = None
    store_tool: str = "_store_result"
    fetch_tool: str = "_get_result"
    describe_tool: str = "_describe_result"
    default_ttl_seconds: int = 30
    max_payload_bytes: int = 65536
    descriptor_kind: str = "gofr.result_ref"


def reset_results_hub_state(state: ResultsHubState) -> None:
    state.protocol_version = 1
    state.hub_service = None
    state.hub_url = None
    state.callback_token = None
    state.store_tool = "_store_result"
    state.fetch_tool = "_get_result"
    state.describe_tool = "_describe_result"
    state.default_ttl_seconds = 30
    state.max_payload_bytes = 65536
    state.descriptor_kind = "gofr.result_ref"


def configure_results_hub_auth(state: ResultsHubState, callback_token: str | None) -> None:
    state.callback_token = callback_token


def _callback_headers(state: ResultsHubState) -> dict[str, str]:
    callback_token = state.callback_token or os.environ.get(GOFR_FIXTURES_HUB_CALLBACK_TOKEN)
    if not callback_token:
        return {}
    return {"Authorization": f"Bearer {callback_token}"}


def register_results_hub(
    state: ResultsHubState,
    *,
    protocol_version: int,
    hub_service: str,
    hub_url: str,
    store_tool: str,
    fetch_tool: str,
    describe_tool: str,
    default_ttl_seconds: int,
    max_payload_bytes: int,
    descriptor_kind: str,
    can_publish: bool,
    can_consume: bool,
    result_types: tuple[str, ...],
) -> dict[str, Any]:
    state.protocol_version = protocol_version
    state.hub_service = hub_service
    state.hub_url = hub_url
    state.store_tool = store_tool
    state.fetch_tool = fetch_tool
    state.describe_tool = describe_tool
    state.default_ttl_seconds = default_ttl_seconds
    state.max_payload_bytes = max_payload_bytes
    state.descriptor_kind = descriptor_kind

    return {
        "accepted": True,
        "protocol_version": protocol_version,
        "can_publish": can_publish,
        "can_consume": can_consume,
        "result_types": list(result_types),
        "notes": "registered",
    }


async def store_result_via_hub(
    state: ResultsHubState,
    *,
    producer_service: str,
    producer_tool: str,
    result_type: str,
    schema_id: str,
    payload: Any,
    summary: str,
    source_args: dict[str, Any],
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    if not state.hub_url:
        raise ValueError("Results hub is not configured")

    async with (
        httpx.AsyncClient(
            headers=_callback_headers(state),
            timeout=_HUB_CALLBACK_TIMEOUT,
        ) as http_client,
        streamable_http_client(state.hub_url, http_client=http_client) as (read, write, _),
        ClientSession(read, write) as client,
    ):
        await client.initialize()
        result = await client.call_tool(
            state.store_tool,
            {
                "protocol_version": state.protocol_version,
                "producer_service": producer_service,
                "producer_tool": producer_tool,
                "result_type": result_type,
                "schema_id": schema_id,
                "payload": payload,
                "summary": summary,
                "source_args": source_args,
                "ttl_seconds": ttl_seconds,
            },
        )

    if result.isError:
        message = result.content[0].text if result.content else "hub call failed"
        raise ValueError(message)
    if not result.content or result.content[0].text is None:
        raise ValueError("Hub response did not include descriptor content")

    data = json.loads(result.content[0].text)
    if not isinstance(data, dict):
        raise ValueError("Hub response was not a JSON object")
    if "descriptor" in data:
        descriptor = data["descriptor"]
        if not isinstance(descriptor, dict):
            raise ValueError("Hub response descriptor was not an object")
        return descriptor
    return data


async def fetch_result_via_hub(
    state: ResultsHubState,
    *,
    descriptor: object,
    expected_result_type: str,
    expected_schema_id: str,
) -> tuple[Any, dict[str, Any]]:
    if not state.hub_url:
        raise ValueError("Results hub is not configured")

    result_ref = ResultDescriptor.validate_reference(descriptor)
    async with (
        httpx.AsyncClient(
            headers=_callback_headers(state),
            timeout=_HUB_CALLBACK_TIMEOUT,
        ) as http_client,
        streamable_http_client(state.hub_url, http_client=http_client) as (read, write, _),
        ClientSession(read, write) as client,
    ):
        await client.initialize()
        result = await client.call_tool(
            state.fetch_tool,
            {
                "protocol_version": state.protocol_version,
                "result_guid": result_ref.result_guid,
                "hub_service": result_ref.hub_service,
                "expected_result_type": expected_result_type,
                "expected_schema_id": expected_schema_id,
            },
        )

    if result.isError:
        message = result.content[0].text if result.content else "hub call failed"
        raise ValueError(message)
    if not result.content or result.content[0].text is None:
        raise ValueError("Hub response did not include payload content")

    data = json.loads(result.content[0].text)
    response = GetResultResponse.model_validate(data)
    return response.payload, response.metadata.model_dump()
