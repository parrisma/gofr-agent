"""Instrument reference-data test MCP service.

Provides 9 tools covering equity lookup, spot prices, and OHLCV history.
All tools call _require_bearer() first; any non-empty bearer token is accepted.
"""

from __future__ import annotations

import csv

from mcp.server.fastmcp import FastMCP

from tests.fixtures.mcp_services._data_loader import DATA_DIR, csv_table
from tests.fixtures.mcp_services._results_hub import (
    ResultsHubState,
    register_results_hub,
    store_result_via_hub,
)
from tests.fixtures.mcp_services._results_hub import (
    configure_results_hub_auth as _configure_results_hub_auth,
)
from tests.fixtures.mcp_services._results_hub import (
    reset_results_hub_state as _reset_results_hub_state,
)
from tests.fixtures.mcp_services._server import _require_bearer

# ---------------------------------------------------------------------------
# Module-level data (loaded once at import)
# ---------------------------------------------------------------------------

_INSTRUMENTS: dict[str, dict] = csv_table("instruments.csv", "ticker")
_SPOT: dict[str, dict] = csv_table("spot_prices.csv", "ticker")


def _load_ohlcv() -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for p in (DATA_DIR / "ohlcv").glob("*.csv"):
        with p.open(newline="", encoding="utf-8") as fh:
            result[p.stem] = list(csv.DictReader(fh))
    return result


_OHLCV: dict[str, list[dict]] = _load_ohlcv()
_RESULTS_HUB = ResultsHubState()


def configure_results_hub_auth(callback_token: str | None) -> None:
    _configure_results_hub_auth(_RESULTS_HUB, callback_token)

# ---------------------------------------------------------------------------
# FastMCP instance
# ---------------------------------------------------------------------------

mcp = FastMCP("instruments-test-service")

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def instrument_lookup(query: str) -> dict | None:
    """Resolve a ticker, ISIN, or name substring to a canonical instrument record.

    Returns None when no match is found.
    """
    _require_bearer()
    q = query.lower()
    for row in _INSTRUMENTS.values():
        if (
            q in row["ticker"].lower()
            or q in row["isin"].lower()
            or q in row["name"].lower()
        ):
            return {
                "ticker": row["ticker"],
                "isin": row["isin"],
                "name": row["name"],
                "exchange": row["exchange"],
                "currency": row["currency"],
            }
    return None


@mcp.tool()
def get_spot_price(ticker: str) -> dict | None:
    """Return the current synthetic mid price for an instrument.

    Returns None for unknown tickers.
    """
    _require_bearer()
    row = _SPOT.get(ticker.upper())
    if row is None:
        return None
    return {
        "ticker": row["ticker"],
        "price": float(row["price"]),
        "currency": row["currency"],
        "as_of": row["as_of"],
    }


@mcp.tool()
def get_price_on_date(ticker: str, date: str) -> dict | None:
    """Return the OHLCV bar for one instrument on one trading date.

    Returns None when there is no bar for the requested date.
    """
    _require_bearer()
    bars = _OHLCV.get(ticker.upper(), [])
    for bar in bars:
        if bar["date"] == date:
            return {
                "ticker": ticker.upper(),
                "date": bar["date"],
                "open": float(bar["open"]),
                "high": float(bar["high"]),
                "low": float(bar["low"]),
                "close": float(bar["close"]),
                "volume": int(bar["volume"]),
            }
    return None


@mcp.tool()
def list_instruments(exchange: str | None = None) -> list[dict]:
    """Return all instruments, optionally filtered by exchange MIC code.

    When exchange is None all instruments are returned.
    """
    _require_bearer()
    rows = list(_INSTRUMENTS.values())
    if exchange is not None:
        rows = [r for r in rows if r["exchange"] == exchange.upper()]
    return [
        {
            "ticker": r["ticker"],
            "isin": r["isin"],
            "name": r["name"],
            "exchange": r["exchange"],
            "currency": r["currency"],
        }
        for r in rows
    ]


@mcp.tool()
async def get_ohlcv_history(ticker: str, from_date: str, to_date: str) -> list[dict] | dict:
    """Return daily OHLCV bars for an instrument over a date range (inclusive).

    Returns bars in ascending date order. Returns [] for unknown tickers or empty ranges.
    """
    _require_bearer()
    bars = _OHLCV.get(ticker.upper(), [])
    result = [
        {
            "date": b["date"],
            "open": float(b["open"]),
            "high": float(b["high"]),
            "low": float(b["low"]),
            "close": float(b["close"]),
            "volume": int(b["volume"]),
        }
        for b in bars
        if from_date <= b["date"] <= to_date
    ]
    sorted_result = sorted(result, key=lambda b: b["date"])
    if _RESULTS_HUB.hub_url is None:
        return sorted_result
    return await store_result_via_hub(
        _RESULTS_HUB,
        producer_service="instruments",
        producer_tool="get_ohlcv_history",
        result_type="ohlcv_bars",
        schema_id="gofr.ohlcv_bars.v1",
        payload=sorted_result,
        summary=f"{len(sorted_result)} OHLCV bars for {ticker.upper()}",
        source_args={
            "ticker": ticker.upper(),
            "from_date": from_date,
            "to_date": to_date,
        },
        ttl_seconds=None,
    )


@mcp.tool(name="_register_results_hub")
def _register_results_hub(
    protocol_version: int,
    hub_service: str,
    hub_url: str,
    store_tool: str,
    fetch_tool: str,
    describe_tool: str,
    default_ttl_seconds: int,
    max_payload_bytes: int,
    descriptor_kind: str,
) -> dict:
    _require_bearer()
    return register_results_hub(
        _RESULTS_HUB,
        protocol_version=protocol_version,
        hub_service=hub_service,
        hub_url=hub_url,
        store_tool=store_tool,
        fetch_tool=fetch_tool,
        describe_tool=describe_tool,
        default_ttl_seconds=default_ttl_seconds,
        max_payload_bytes=max_payload_bytes,
        descriptor_kind=descriptor_kind,
        can_publish=True,
        can_consume=True,
        result_types=("ohlcv_bars",),
    )


@mcp.tool()
def get_volume_history(ticker: str, from_date: str, to_date: str) -> list[dict]:
    """Return daily volume only for an instrument over a date range.

    Each item contains only ticker, date, and volume.
    Returns [] for unknown tickers or empty ranges.
    """
    _require_bearer()
    bars = _OHLCV.get(ticker.upper(), [])
    result = [
        {
            "ticker": ticker.upper(),
            "date": b["date"],
            "volume": int(b["volume"]),
        }
        for b in bars
        if from_date <= b["date"] <= to_date
    ]
    return sorted(result, key=lambda b: b["date"])


@mcp.tool()
def get_latest_trading_day(ticker: str) -> dict | None:
    """Return the latest available trading day for one instrument.

    Returns None for unknown tickers.
    """
    _require_bearer()
    bars = _OHLCV.get(ticker.upper())
    if not bars:
        return None
    latest = max(bars, key=lambda b: b["date"])
    return {"ticker": ticker.upper(), "date": latest["date"]}


@mcp.tool()
def get_market_codes(ticker: str) -> dict | None:
    """Return exchange and market-segment codes for an instrument.

    Returns None for unknown tickers.
    """
    _require_bearer()
    row = _INSTRUMENTS.get(ticker.upper())
    if row is None:
        return None
    return {
        "ticker": row["ticker"],
        "primary_mic": row["exchange"],
        "bloomberg_code": row["bloomberg_code"],
        "reuters_ric": row["reuters_ric"],
        "sedol": row["sedol"],
    }


@mcp.tool()
def validate_market_code(ticker: str, exchange: str) -> dict:
    """Check whether an instrument's primary exchange matches the supplied MIC.

    Returns a record indicating whether the exchange is the primary listing venue.
    """
    _require_bearer()
    row = _INSTRUMENTS.get(ticker.upper())
    primary = row["exchange"] if row is not None else ""
    return {
        "ticker": ticker.upper(),
        "exchange": exchange.upper(),
        "primary_exchange": primary,
        "is_match": primary == exchange.upper(),
    }


def reset_results_hub_state() -> None:
    _reset_results_hub_state(_RESULTS_HUB)
