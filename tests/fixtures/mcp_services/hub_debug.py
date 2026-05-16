"""Test MCP service that calls back into gofr-agent's results hub."""

from __future__ import annotations

import json

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP

from tests.fixtures.mcp_services._server import _require_bearer

_HUB_URL: str | None = None
_CALLBACK_TOKEN: str | None = None
_PRODUCER_SERVICE = "hub-fixture"


def configure_results_hub(
    hub_url: str | None,
    callback_token: str | None,
    producer_service: str = "hub-fixture",
) -> None:
    global _HUB_URL, _CALLBACK_TOKEN, _PRODUCER_SERVICE
    _HUB_URL = hub_url
    _CALLBACK_TOKEN = callback_token
    _PRODUCER_SERVICE = producer_service


async def _debug_reentrant_store_result(series_id: str = "series-1") -> dict[str, object]:
    """Store a small payload in gofr-agent before returning to the original caller."""
    _require_bearer()
    if not _HUB_URL:
        raise ValueError("Hub URL is not configured")

    headers: dict[str, str] = {}
    if _CALLBACK_TOKEN is not None:
        headers["Authorization"] = f"Bearer {_CALLBACK_TOKEN}"

    payload = [
        {
            "date": "2026-05-12",
            "open": 100.0,
            "high": 101.0,
            "low": 99.5,
            "close": 100.5,
            "volume": 1200,
            "series_id": series_id,
            "raw_marker": "reentrant-raw-payload-marker",
        },
        {
            "date": "2026-05-13",
            "open": 100.5,
            "high": 102.0,
            "low": 100.0,
            "close": 101.5,
            "volume": 1300,
            "series_id": series_id,
            "raw_marker": "reentrant-raw-payload-marker",
        },
    ]

    async with (
        streamablehttp_client(_HUB_URL, headers=headers) as (read, write, _),
        ClientSession(read, write) as client,
    ):
        await client.initialize()
        result = await client.call_tool(
            "_store_result",
            {
                "protocol_version": 1,
                "producer_service": _PRODUCER_SERVICE,
                "producer_tool": "debug_reentrant_store_result",
                "result_type": "ohlcv_bars",
                "schema_id": "gofr.ohlcv_bars.v1",
                "payload": payload,
                "summary": "2 bars for reentrancy validation",
                "source_args": {"series_id": series_id},
                "ttl_seconds": 30,
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


def build_mcp() -> FastMCP:
    mcp = FastMCP("hub-debug-test-service")
    mcp.tool(name="debug_reentrant_store_result")(_debug_reentrant_store_result)
    return mcp


mcp = build_mcp()
