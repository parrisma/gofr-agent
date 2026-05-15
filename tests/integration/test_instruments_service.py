"""Integration tests for the Instrument test MCP service."""

from __future__ import annotations

import json

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _parse_item(text: str) -> object:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


async def _call_json(url: str, tool: str, args: dict, *, headers: dict | None = None) -> object:
    h = headers if headers is not None else AUTH_HEADERS
    async with (
        streamablehttp_client(url, headers=h) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool(tool, arguments=args)
    content = result.content
    if len(content) == 0:
        return None
    if len(content) == 1:
        return _parse_item(content[0].text)
    # FastMCP serialises list return values as one content block per element
    return [_parse_item(item.text) for item in content]


# ---------------------------------------------------------------------------
# 1. Auth guard
# ---------------------------------------------------------------------------


async def test_instrument_lookup_no_token_raises(instruments_url: str) -> None:
    """Calling any tool without a bearer token must produce an error."""
    async with (
        streamablehttp_client(instruments_url, headers={}) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool("instrument_lookup", arguments={"query": "AAPL"})
    # Tool raises ValueError which FastMCP returns as an error content block
    assert result.isError or len(result.content) > 0
    if result.content:
        text = result.content[0].text.lower()
        assert "authorization" in text or "bearer" in text or "error" in text


# ---------------------------------------------------------------------------
# 2. instrument_lookup
# ---------------------------------------------------------------------------


async def test_instrument_lookup_by_ticker(instruments_url: str) -> None:
    result = await _call_json(instruments_url, "instrument_lookup", {"query": "AAPL"})
    assert result is not None
    assert result["isin"] == "US0378331005"
    assert result["exchange"] == "XNAS"


async def test_instrument_lookup_by_isin(instruments_url: str) -> None:
    result = await _call_json(instruments_url, "instrument_lookup", {"query": "GB0031348658"})
    assert result is not None
    assert result["ticker"] == "BARC"


async def test_instrument_lookup_by_name_substring(instruments_url: str) -> None:
    result = await _call_json(instruments_url, "instrument_lookup", {"query": "vodafone"})
    assert result is not None
    assert result["ticker"] == "VOD"


async def test_instrument_lookup_unknown_returns_none(instruments_url: str) -> None:
    result = await _call_json(instruments_url, "instrument_lookup", {"query": "ZZZZ"})
    assert result is None


# ---------------------------------------------------------------------------
# 3. get_spot_price
# ---------------------------------------------------------------------------


async def test_get_spot_price_known(instruments_url: str) -> None:
    result = await _call_json(instruments_url, "get_spot_price", {"ticker": "NVDA"})
    assert result is not None
    assert result["price"] == pytest.approx(875.20)
    assert result["currency"] == "USD"


async def test_get_spot_price_unknown_returns_none(instruments_url: str) -> None:
    result = await _call_json(instruments_url, "get_spot_price", {"ticker": "ZZZZ"})
    assert result is None


# ---------------------------------------------------------------------------
# 4. get_price_on_date
# ---------------------------------------------------------------------------


async def test_get_price_on_date_returns_bar(instruments_url: str) -> None:
    # 2026-01-08 is the first bar in AAPL.csv
    result = await _call_json(
        instruments_url, "get_price_on_date", {"ticker": "AAPL", "date": "2026-01-08"}
    )
    assert result is not None
    for key in ("open", "high", "low", "close", "volume"):
        assert key in result
    assert isinstance(result["open"], float)
    assert isinstance(result["volume"], int)


async def test_get_price_on_date_unknown_date_returns_none(instruments_url: str) -> None:
    result = await _call_json(
        instruments_url, "get_price_on_date", {"ticker": "AAPL", "date": "1990-01-01"}
    )
    assert result is None


# ---------------------------------------------------------------------------
# 5. list_instruments
# ---------------------------------------------------------------------------


async def test_list_instruments_all(instruments_url: str) -> None:
    result = await _call_json(instruments_url, "list_instruments", {})
    assert isinstance(result, list)
    assert len(result) == 6


async def test_list_instruments_by_exchange(instruments_url: str) -> None:
    result = await _call_json(instruments_url, "list_instruments", {"exchange": "XLON"})
    assert isinstance(result, list)
    assert len(result) == 2
    assert all(r["exchange"] == "XLON" for r in result)


async def test_list_instruments_no_exchange_returns_all(instruments_url: str) -> None:
    result = await _call_json(instruments_url, "list_instruments", {"exchange": None})
    assert isinstance(result, list)
    assert len(result) == 6


# ---------------------------------------------------------------------------
# 6. get_ohlcv_history
# ---------------------------------------------------------------------------


async def test_get_ohlcv_history_returns_ordered_bars(instruments_url: str) -> None:
    result = await _call_json(
        instruments_url,
        "get_ohlcv_history",
        {"ticker": "MSFT", "from_date": "2026-02-01", "to_date": "2026-02-28"},
    )
    assert isinstance(result, list)
    assert len(result) > 0
    dates = [b["date"] for b in result]
    assert dates == sorted(dates)
    for bar in result:
        for key in ("date", "open", "high", "low", "close", "volume"):
            assert key in bar


async def test_get_ohlcv_history_unknown_ticker_returns_empty(instruments_url: str) -> None:
    result = await _call_json(
        instruments_url,
        "get_ohlcv_history",
        {"ticker": "ZZZZ", "from_date": "2026-01-01", "to_date": "2026-05-01"},
    )
    # FastMCP serialises both None and [] as 0 content items
    assert result is None or result == []


async def test_get_ohlcv_history_out_of_range_returns_empty(instruments_url: str) -> None:
    result = await _call_json(
        instruments_url,
        "get_ohlcv_history",
        {"ticker": "AAPL", "from_date": "2020-01-01", "to_date": "2020-12-31"},
    )
    # FastMCP serialises both None and [] as 0 content items
    assert result is None or result == []


# ---------------------------------------------------------------------------
# 7. get_volume_history
# ---------------------------------------------------------------------------


async def test_get_volume_history_only_has_date_and_volume(instruments_url: str) -> None:
    result = await _call_json(
        instruments_url,
        "get_volume_history",
        {"ticker": "TSLA", "from_date": "2026-03-01", "to_date": "2026-03-31"},
    )
    assert isinstance(result, list)
    assert len(result) > 0
    for item in result:
        assert set(item.keys()) == {"ticker", "date", "volume"}
        assert "close" not in item
        assert "open" not in item


# ---------------------------------------------------------------------------
# 8. get_latest_trading_day
# ---------------------------------------------------------------------------


async def test_get_latest_trading_day(instruments_url: str) -> None:
    result = await _call_json(instruments_url, "get_latest_trading_day", {"ticker": "AAPL"})
    assert result is not None
    assert result["date"] == "2026-05-13"


# ---------------------------------------------------------------------------
# 9. get_market_codes
# ---------------------------------------------------------------------------


async def test_get_market_codes_nasdaq(instruments_url: str) -> None:
    result = await _call_json(instruments_url, "get_market_codes", {"ticker": "AAPL"})
    assert result is not None
    assert result["primary_mic"] == "XNAS"
    assert result["bloomberg_code"] == "AAPL US Equity"
    assert result["reuters_ric"] == "AAPL.O"


async def test_get_market_codes_lse(instruments_url: str) -> None:
    result = await _call_json(instruments_url, "get_market_codes", {"ticker": "BARC"})
    assert result is not None
    assert result["primary_mic"] == "XLON"


async def test_get_market_codes_unknown_returns_none(instruments_url: str) -> None:
    result = await _call_json(instruments_url, "get_market_codes", {"ticker": "ZZZZ"})
    assert result is None


# ---------------------------------------------------------------------------
# 10. validate_market_code
# ---------------------------------------------------------------------------


async def test_validate_market_code_match(instruments_url: str) -> None:
    result = await _call_json(
        instruments_url, "validate_market_code", {"ticker": "AAPL", "exchange": "XNAS"}
    )
    assert result["is_match"] is True


async def test_validate_market_code_no_match(instruments_url: str) -> None:
    result = await _call_json(
        instruments_url, "validate_market_code", {"ticker": "AAPL", "exchange": "XLON"}
    )
    assert result["is_match"] is False
    assert result["primary_exchange"] == "XNAS"
