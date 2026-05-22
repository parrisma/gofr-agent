"""Integration tests for the Trade test MCP service."""

from __future__ import annotations

import json

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from tests.fixtures.mcp_services._data_loader import csv_rows
from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helper (same pattern as other service tests)
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
    return [_parse_item(item.text) for item in content]


# ---------------------------------------------------------------------------
# 1. Auth guard
# ---------------------------------------------------------------------------


async def test_get_trades_no_token_raises(trades_url: str) -> None:
    async with (
        streamablehttp_client(trades_url, headers={}) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool("get_trades", arguments={})
    assert result.isError or len(result.content) > 0
    if result.content:
        text = result.content[0].text.lower()
        assert "authorization" in text or "bearer" in text or "error" in text


# ---------------------------------------------------------------------------
# 2. get_trades filtering
# ---------------------------------------------------------------------------


async def test_get_trades_by_client(trades_url: str) -> None:
    result = await _call_json(trades_url, "get_trades", {"client_id": "C001"})
    assert isinstance(result, list)
    assert len(result) >= 5
    assert all(r["client_id"] == "C001" for r in result)


async def test_get_trades_by_ticker(trades_url: str) -> None:
    result = await _call_json(trades_url, "get_trades", {"ticker": "NVDA"})
    assert isinstance(result, list)
    assert all(r["ticker"] == "NVDA" for r in result)


async def test_get_trades_by_client_and_ticker(trades_url: str) -> None:
    result = await _call_json(trades_url, "get_trades", {"client_id": "C002", "ticker": "AAPL"})
    assert isinstance(result, list)
    trade_ids = {r["trade_id"] for r in result}
    assert "T0005" in trade_ids
    assert "T0006" in trade_ids


async def test_get_trades_date_filter(trades_url: str) -> None:
    result = await _call_json(
        trades_url,
        "get_trades",
        {"from_date": "2026-03-01", "to_date": "2026-03-31"},
    )
    assert isinstance(result, list)
    assert all("2026-03-01" <= r["trade_date"] <= "2026-03-31" for r in result)


async def test_get_trades_no_filter_returns_all(trades_url: str) -> None:
    result = await _call_json(trades_url, "get_trades", {})
    assert isinstance(result, list)
    assert len(result) == len(csv_rows("trades.csv"))


# ---------------------------------------------------------------------------
# 3. get_trade
# ---------------------------------------------------------------------------


async def test_get_trade_known(trades_url: str) -> None:
    result = await _call_json(trades_url, "get_trade", {"trade_id": "T0007"})
    assert result is not None
    assert result["client_id"] == "C002"
    assert result["ticker"] == "NVDA"
    assert result["side"] == "buy"
    assert result["price"] == pytest.approx(820.00)


async def test_get_trade_unknown_returns_none(trades_url: str) -> None:
    result = await _call_json(trades_url, "get_trade", {"trade_id": "T9999"})
    assert result is None


# ---------------------------------------------------------------------------
# 4. get_last_trade
# ---------------------------------------------------------------------------


async def test_get_last_trade_c002_nvda(trades_url: str) -> None:
    # T0008 (2026-04-10) is later than T0007 (2026-02-18)
    result = await _call_json(trades_url, "get_last_trade", {"client_id": "C002", "ticker": "NVDA"})
    assert result is not None
    assert result["trade_date"] == "2026-04-10"


async def test_get_last_trade_no_trades_returns_none(trades_url: str) -> None:
    # C001 never traded MSFT
    result = await _call_json(trades_url, "get_last_trade", {"client_id": "C001", "ticker": "MSFT"})
    assert result is None


# ---------------------------------------------------------------------------
# 5. list_clients_traded_instrument
# ---------------------------------------------------------------------------


async def test_list_clients_traded_aapl(trades_url: str) -> None:
    result = await _call_json(trades_url, "list_clients_traded_instrument", {"ticker": "AAPL"})
    assert isinstance(result, list)
    assert "C001" in result
    assert "C002" in result
    assert "C003" in result


async def test_list_clients_traded_aapl_date_filter(trades_url: str) -> None:
    # T0006 C002 sell 2026-04-15, T0014 C003 sell 2026-04-30 — both in range
    # C001 AAPL: T0001 2026-02-16, T0002 2026-03-23 — both before April
    result = await _call_json(
        trades_url,
        "list_clients_traded_instrument",
        {"ticker": "AAPL", "from_date": "2026-04-01", "to_date": "2026-05-01"},
    )
    assert isinstance(result, list)
    assert "C002" in result
    assert "C003" in result
    assert "C001" not in result


async def test_list_clients_traded_unknown_ticker(trades_url: str) -> None:
    result = await _call_json(trades_url, "list_clients_traded_instrument", {"ticker": "ZZZZ"})
    assert result is None or result == []


# ---------------------------------------------------------------------------
# 6. get_trade_activity_window
# ---------------------------------------------------------------------------


async def test_get_trade_activity_window_c001(trades_url: str) -> None:
    result = await _call_json(
        trades_url,
        "get_trade_activity_window",
        {"client_id": "C001", "from_date": "2026-02-01", "to_date": "2026-05-13"},
    )
    assert isinstance(result, list)
    assert len(result) >= 3  # AAPL, BARC, VOD, NVDA, TSLA all present
    for entry in result:
        assert entry["trade_count"] >= 1


# ---------------------------------------------------------------------------
# 7. get_trade_summary
# ---------------------------------------------------------------------------


async def test_get_trade_summary_c002_aapl(trades_url: str) -> None:
    # T0005 buy 2000 @ 178.50; T0006 sell 2000 @ 194.20
    result = await _call_json(
        trades_url, "get_trade_summary", {"client_id": "C002", "ticker": "AAPL"}
    )
    assert result is not None
    assert result["total_buys"] == 1
    assert result["total_sells"] == 1
    assert result["net_quantity"] == 0
    assert result["avg_buy_price"] == pytest.approx(178.50)
    assert result["avg_sell_price"] == pytest.approx(194.20)


async def test_get_trade_summary_no_trades(trades_url: str) -> None:
    # C001 never traded MSFT
    result = await _call_json(
        trades_url, "get_trade_summary", {"client_id": "C001", "ticker": "MSFT"}
    )
    assert result is not None
    assert result["total_buys"] == 0
    assert result["total_sells"] == 0
    assert result["net_quantity"] == 0


# ---------------------------------------------------------------------------
# 8. get_average_execution_price
# ---------------------------------------------------------------------------


async def test_get_average_execution_price_buy_side(trades_url: str) -> None:
    result = await _call_json(
        trades_url,
        "get_average_execution_price",
        {"client_id": "C002", "ticker": "AAPL", "side": "buy"},
    )
    assert result is not None
    assert result["avg_price"] == pytest.approx(178.50)
    assert result["total_quantity"] == 2000


async def test_get_average_execution_price_both_sides(trades_url: str) -> None:
    result = await _call_json(
        trades_url,
        "get_average_execution_price",
        {"client_id": "C002", "ticker": "AAPL", "side": None},
    )
    assert result is not None
    assert result["trade_count"] == 2


# ---------------------------------------------------------------------------
# 9. get_realised_pnl
# ---------------------------------------------------------------------------


async def test_get_realised_pnl_c002_aapl(trades_url: str) -> None:
    # T0005 buy 2000 @ 178.50; T0006 sell 2000 @ 194.20
    # PnL = (194.20 - 178.50) * 2000 = 31400.00
    result = await _call_json(
        trades_url, "get_realised_pnl", {"client_id": "C002", "ticker": "AAPL"}
    )
    assert result is not None
    assert result["realised_pnl"] == pytest.approx(31400.00, abs=0.01)
    assert result["matched_trades"] == 1


async def test_get_realised_pnl_partial_round_trip(trades_url: str) -> None:
    # C001/AAPL: T0001 buy 1000 @ 182.10; T0002 sell 500 @ 191.30
    # PnL = (191.30 - 182.10) * 500 = 4600.00
    result = await _call_json(
        trades_url, "get_realised_pnl", {"client_id": "C001", "ticker": "AAPL"}
    )
    assert result is not None
    assert result["realised_pnl"] == pytest.approx(4600.00, abs=0.01)
    assert result["matched_trades"] == 1


async def test_get_realised_pnl_no_sells_returns_zero(trades_url: str) -> None:
    # C001/VOD: T0004 buy only
    result = await _call_json(
        trades_url, "get_realised_pnl", {"client_id": "C001", "ticker": "VOD"}
    )
    assert result is not None
    assert result["realised_pnl"] == pytest.approx(0.0)
    assert result["matched_trades"] == 0


# ---------------------------------------------------------------------------
# 10. list_traded_instruments
# ---------------------------------------------------------------------------


async def test_list_traded_instruments_c001(trades_url: str) -> None:
    result = await _call_json(trades_url, "list_traded_instruments", {"client_id": "C001"})
    assert isinstance(result, list)
    assert "AAPL" in result
    assert "BARC" in result
    assert "NVDA" in result
    assert "TSLA" in result
    assert "VOD" in result


async def test_list_traded_instruments_unknown_client(trades_url: str) -> None:
    result = await _call_json(trades_url, "list_traded_instruments", {"client_id": "ZZZZ"})
    assert result is None or result == []
