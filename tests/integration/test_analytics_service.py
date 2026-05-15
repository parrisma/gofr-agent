"""Integration tests for the Analytics test MCP service."""

from __future__ import annotations

import json

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

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
# Bar construction helpers
# ---------------------------------------------------------------------------


def _make_bar(date: str, close: float, vol: int = 1_000_000) -> dict:
    """Build a minimal OHLCV bar with close = open = high = low for simplicity."""
    return {
        "date": date,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": vol,
    }


def _make_bars(closes: list[float], start_date_offset: int = 0) -> list[dict]:
    """Build a sequence of bars from a list of close prices, labelled with fake dates."""
    dates = [f"2026-01-{i+1+start_date_offset:02d}" for i in range(len(closes))]
    return [_make_bar(d, c) for d, c in zip(dates, closes, strict=True)]


# ---------------------------------------------------------------------------
# 1. Auth guard
# ---------------------------------------------------------------------------


async def test_historical_volatility_no_token_raises(analytics_url: str) -> None:
    bars = [_make_bar("2026-01-01", 100.0)]
    async with (
        streamablehttp_client(analytics_url, headers={}) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool(
            "historical_volatility", arguments={"ticker": "AAPL", "bars": bars}
        )
    assert result.isError or len(result.content) > 0
    if result.content:
        text = result.content[0].text.lower()
        assert "authorization" in text or "bearer" in text or "error" in text


# ---------------------------------------------------------------------------
# 2. historical_volatility
# ---------------------------------------------------------------------------


async def test_historical_volatility_sufficient_data(analytics_url: str) -> None:
    # 25 bars with alternating returns to ensure non-zero variance
    closes = [100.0]
    for i in range(24):
        closes.append(closes[-1] * (1.01 if i % 2 == 0 else 0.993))
    bars = _make_bars(closes)
    result = await _call_json(
        analytics_url,
        "historical_volatility",
        {"ticker": "AAPL", "bars": bars, "window": 20},
    )
    assert result is not None
    assert result["annualised_vol"] is not None
    assert isinstance(result["annualised_vol"], float)
    assert result["annualised_vol"] > 0
    assert result["observations"] == 20


async def test_historical_volatility_insufficient_data(analytics_url: str) -> None:
    bars = _make_bars([100.0, 101.0, 102.0, 103.0, 104.0])  # 5 bars
    result = await _call_json(
        analytics_url,
        "historical_volatility",
        {"ticker": "AAPL", "bars": bars, "window": 20},
    )
    assert result is not None
    assert result["annualised_vol"] is None
    assert result["observations"] == 0


# ---------------------------------------------------------------------------
# 3. vwap
# ---------------------------------------------------------------------------


async def test_vwap_simple(analytics_url: str) -> None:
    # 3 bars, typical price = (o+h+l+c)/4 = close (since we set all equal)
    # bar1: close=100, vol=1000 → pv=100000
    # bar2: close=200, vol=2000 → pv=400000
    # bar3: close=300, vol=3000 → pv=900000
    # vwap = 1400000 / 6000 ≈ 233.3333
    bars = [
        {"date": "2026-01-01", "open": 100.0, "high": 100.0, "low": 100.0,
         "close": 100.0, "volume": 1000},
        {"date": "2026-01-02", "open": 200.0, "high": 200.0, "low": 200.0,
         "close": 200.0, "volume": 2000},
        {"date": "2026-01-03", "open": 300.0, "high": 300.0, "low": 300.0,
         "close": 300.0, "volume": 3000},
    ]
    result = await _call_json(analytics_url, "vwap", {"ticker": "AAPL", "bars": bars})
    assert result is not None
    expected_vwap = (100.0 * 1000 + 200.0 * 2000 + 300.0 * 3000) / (1000 + 2000 + 3000)
    assert result["vwap"] == pytest.approx(expected_vwap, rel=1e-4)
    assert result["total_volume"] == 6000


async def test_vwap_from_to_dates(analytics_url: str) -> None:
    bars = [_make_bar("2026-02-01", 150.0), _make_bar("2026-02-28", 160.0)]
    result = await _call_json(analytics_url, "vwap", {"ticker": "MSFT", "bars": bars})
    assert result is not None
    assert result["from_date"] == "2026-02-01"
    assert result["to_date"] == "2026-02-28"


# ---------------------------------------------------------------------------
# 4. simple_return
# ---------------------------------------------------------------------------


async def test_simple_return_positive(analytics_url: str) -> None:
    bars = [_make_bar("2026-01-01", 100.0), _make_bar("2026-01-31", 110.0)]
    result = await _call_json(analytics_url, "simple_return", {"ticker": "AAPL", "bars": bars})
    assert result is not None
    assert result["return_pct"] == pytest.approx(10.0, rel=1e-5)
    assert result["from_price"] == 100.0
    assert result["to_price"] == 110.0


async def test_simple_return_negative(analytics_url: str) -> None:
    bars = [_make_bar("2026-01-01", 200.0), _make_bar("2026-01-31", 190.0)]
    result = await _call_json(analytics_url, "simple_return", {"ticker": "TSLA", "bars": bars})
    assert result is not None
    assert result["return_pct"] == pytest.approx(-5.0, rel=1e-5)


# ---------------------------------------------------------------------------
# 5. max_drawdown
# ---------------------------------------------------------------------------


async def test_max_drawdown_falling_sequence(analytics_url: str) -> None:
    # closes = [100, 120, 80, 90, 70, 110]
    # peak=120 at bar1; trough=70 at bar4; dd = (70-120)/120 * 100 = -41.6667%
    closes = [100.0, 120.0, 80.0, 90.0, 70.0, 110.0]
    bars = _make_bars(closes)
    result = await _call_json(analytics_url, "max_drawdown", {"ticker": "AAPL", "bars": bars})
    assert result is not None
    assert result["max_drawdown_pct"] == pytest.approx(-41.6667, rel=1e-3)
    assert result["peak_close"] == pytest.approx(120.0)
    assert result["trough_close"] == pytest.approx(70.0)


async def test_max_drawdown_monotone_rising(analytics_url: str) -> None:
    closes = [100.0, 110.0, 120.0, 130.0, 140.0]
    bars = _make_bars(closes)
    result = await _call_json(analytics_url, "max_drawdown", {"ticker": "AAPL", "bars": bars})
    assert result is not None
    assert result["max_drawdown_pct"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 6. price_momentum
# ---------------------------------------------------------------------------


async def test_price_momentum_above_ma(analytics_url: str) -> None:
    # 25 bars with linearly increasing closes so last close > 20-day MA
    closes = [100.0 + i for i in range(25)]  # 100, 101, ..., 124
    bars = _make_bars(closes)
    result = await _call_json(
        analytics_url, "price_momentum", {"ticker": "AAPL", "bars": bars, "window": 20}
    )
    assert result is not None
    assert result["signal"] == "above_ma"


async def test_price_momentum_insufficient_data(analytics_url: str) -> None:
    bars = _make_bars([100.0, 101.0, 102.0, 103.0, 104.0])  # 5 bars
    result = await _call_json(
        analytics_url, "price_momentum", {"ticker": "AAPL", "bars": bars, "window": 20}
    )
    assert result is not None
    assert result["signal"] == "insufficient_data"


# ---------------------------------------------------------------------------
# 7. position_market_value
# ---------------------------------------------------------------------------


async def test_position_market_value_long(analytics_url: str) -> None:
    result = await _call_json(
        analytics_url,
        "position_market_value",
        {
            "client_id": "C001",
            "ticker": "AAPL",
            "quantity": 5000,
            "spot_price": 189.45,
            "currency": "USD",
        },
    )
    assert result is not None
    assert result["market_value"] == pytest.approx(947250.0, rel=1e-4)


async def test_position_market_value_short(analytics_url: str) -> None:
    result = await _call_json(
        analytics_url,
        "position_market_value",
        {
            "client_id": "C002",
            "ticker": "TSLA",
            "quantity": -1000,
            "spot_price": 172.60,
            "currency": "USD",
        },
    )
    assert result is not None
    assert result["market_value"] == pytest.approx(-172600.0, rel=1e-4)


# ---------------------------------------------------------------------------
# 8. compare_execution_to_vwap
# ---------------------------------------------------------------------------


async def test_compare_execution_to_vwap_buy_favourable(analytics_url: str) -> None:
    # Buy exec 178.50 < vwap 180.00 → favourable
    # bps = (178.50 - 180.00) / 180.00 * 10000 ≈ -83.33
    result = await _call_json(
        analytics_url,
        "compare_execution_to_vwap",
        {"ticker": "AAPL", "side": "buy", "execution_price": 178.50, "vwap_price": 180.00},
    )
    assert result is not None
    assert result["favourable"] is True
    assert result["basis_points"] == pytest.approx(-83.33, rel=1e-2)


async def test_compare_execution_to_vwap_sell_favourable(analytics_url: str) -> None:
    # Sell exec 194.20 > vwap 190.00 → favourable
    result = await _call_json(
        analytics_url,
        "compare_execution_to_vwap",
        {"ticker": "AAPL", "side": "sell", "execution_price": 194.20, "vwap_price": 190.00},
    )
    assert result is not None
    assert result["favourable"] is True


async def test_compare_execution_to_vwap_buy_unfavourable(analytics_url: str) -> None:
    # Buy exec 195.00 > vwap 190.00 → unfavourable
    result = await _call_json(
        analytics_url,
        "compare_execution_to_vwap",
        {"ticker": "AAPL", "side": "buy", "execution_price": 195.00, "vwap_price": 190.00},
    )
    assert result is not None
    assert result["favourable"] is False
