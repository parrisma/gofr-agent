"""Analytics test MCP service.

Provides 7 stateless tools for computing derived market metrics.
All tools call _require_bearer() first; any non-empty bearer token is accepted.
Bars may be supplied inline or via results-hub descriptors.
"""

from __future__ import annotations

import math
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from app.hub.models import ResultDescriptor
from tests.fixtures.mcp_services._results_hub import (
    ResultsHubState,
    fetch_result_via_hub,
    register_results_hub,
)
from tests.fixtures.mcp_services._results_hub import (
    configure_results_hub_auth as _configure_results_hub_auth,
)
from tests.fixtures.mcp_services._results_hub import (
    reset_results_hub_state as _reset_results_hub_state,
)
from tests.fixtures.mcp_services._server import _require_bearer

# ---------------------------------------------------------------------------
# FastMCP instance
# ---------------------------------------------------------------------------

mcp = FastMCP("analytics-test-service")
_RESULTS_HUB = ResultsHubState()
_BAR_SCHEMA_ID = "gofr.ohlcv_bars.v1"
_BAR_FIELDS = {"date", "open", "high", "low", "close", "volume"}
_BarsRef = Annotated[
    ResultDescriptor | dict[str, Any] | str | None,
    Field(
        description=(
            "Descriptor returned by instruments__get_ohlcv_history. Pass the object "
            "verbatim; a JSON-serialized descriptor is also accepted."
        ),
        json_schema_extra={"x-gofr-result-descriptor": True},
    ),
]


def configure_results_hub_auth(callback_token: str | None) -> None:
    _configure_results_hub_auth(_RESULTS_HUB, callback_token)


def reset_results_hub_state() -> None:
    _reset_results_hub_state(_RESULTS_HUB)


def _normalise_bars(payload: Any) -> list[dict]:
    if not isinstance(payload, list):
        raise ValueError("OHLCV payload must be a list of bars")

    normalised: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("OHLCV payload items must be JSON objects")
        missing = sorted(_BAR_FIELDS - item.keys())
        if missing:
            missing_fields = ", ".join(missing)
            raise ValueError(f"OHLCV payload missing required fields: {missing_fields}")
        normalised.append(
            {
                "date": str(item["date"]),
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
                "volume": int(item["volume"]),
            }
        )
    return normalised


async def _resolve_bars(bars: list[dict] | None, bars_ref: object | None) -> list[dict]:
    if bars_ref is not None:
        payload, _metadata = await fetch_result_via_hub(
            _RESULTS_HUB,
            descriptor=bars_ref,
            expected_result_type="ohlcv_bars",
            expected_schema_id=_BAR_SCHEMA_ID,
        )
        return _normalise_bars(payload)
    if bars is None:
        raise ValueError("Provide bars or bars_ref")
    return _normalise_bars(bars)

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def historical_volatility(
    ticker: str,
    bars: list[dict] | None = None,
    bars_ref: _BarsRef = None,
    window: int = 20,
) -> dict:
    """Compute annualised close-to-close historical volatility (std of log returns * sqrt(252)).

    `bars` may be supplied inline or via `bars_ref` from
    `instruments__get_ohlcv_history`; this tool does not accept date ranges alone.
    Returns annualised_vol=None and observations=0 when fewer than window+1 bars are supplied.
    """
    _require_bearer()
    bars = await _resolve_bars(bars, bars_ref)
    closes = [float(b["close"]) for b in bars]
    if len(closes) < window + 1:
        return {
            "ticker": ticker,
            "window": window,
            "annualised_vol": None,
            "as_of": bars[-1]["date"] if bars else None,
            "observations": 0,
        }
    log_rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    used = log_rets[-window:]
    mean = sum(used) / len(used)
    variance = sum((r - mean) ** 2 for r in used) / (len(used) - 1)
    annualised_vol = math.sqrt(variance) * math.sqrt(252)
    return {
        "ticker": ticker,
        "window": window,
        "annualised_vol": round(annualised_vol, 6),
        "as_of": bars[-1]["date"],
        "observations": len(used),
    }


@mcp.tool()
async def vwap(
    ticker: str,
    bars: list[dict] | None = None,
    bars_ref: _BarsRef = None,
) -> dict:
    """Compute the volume-weighted average price over the supplied bars.

    `bars` may be supplied inline or via `bars_ref` from
    `instruments__get_ohlcv_history`.
    Uses (open + high + low + close) / 4 as the typical price per bar.
    """
    _require_bearer()
    bars = await _resolve_bars(bars, bars_ref)
    total_vol = sum(int(b["volume"]) for b in bars)
    total_pv = sum(
        ((float(b["open"]) + float(b["high"]) + float(b["low"]) + float(b["close"])) / 4)
        * int(b["volume"])
        for b in bars
    )
    vwap_price = total_pv / total_vol if total_vol > 0 else 0.0
    return {
        "ticker": ticker,
        "vwap": round(vwap_price, 6),
        "from_date": bars[0]["date"],
        "to_date": bars[-1]["date"],
        "total_volume": total_vol,
    }


@mcp.tool()
async def simple_return(
    ticker: str,
    bars: list[dict] | None = None,
    bars_ref: _BarsRef = None,
) -> dict:
    """Compute the total simple price return between the first and last bar close.

    `bars` may be supplied inline or via `bars_ref` from
    `instruments__get_ohlcv_history`; this tool does not accept date ranges alone.
    return_pct = (to_price / from_price - 1) * 100
    """
    _require_bearer()
    bars = await _resolve_bars(bars, bars_ref)
    from_price = float(bars[0]["close"])
    to_price = float(bars[-1]["close"])
    return_pct = (to_price / from_price - 1) * 100
    return {
        "ticker": ticker,
        "from_date": bars[0]["date"],
        "to_date": bars[-1]["date"],
        "from_price": from_price,
        "to_price": to_price,
        "return_pct": round(return_pct, 6),
    }


@mcp.tool()
async def max_drawdown(
    ticker: str,
    bars: list[dict] | None = None,
    bars_ref: _BarsRef = None,
) -> dict:
    """Compute maximum peak-to-trough drawdown over the supplied bars.

    `bars` may be supplied inline or via `bars_ref` from
    `instruments__get_ohlcv_history`; this tool does not accept date ranges alone.
    Drawdown is expressed as a percentage (negative = loss).
    """
    _require_bearer()
    bars = await _resolve_bars(bars, bars_ref)
    peak_close = float("-inf")
    peak_date = bars[0]["date"]
    max_dd_pct = 0.0
    dd_peak_close = float(bars[0]["close"])
    dd_peak_date = bars[0]["date"]
    dd_trough_close = float(bars[0]["close"])
    dd_trough_date = bars[0]["date"]

    for bar in bars:
        close = float(bar["close"])
        if close > peak_close:
            peak_close = close
            peak_date = bar["date"]
        dd = (close - peak_close) / peak_close * 100
        if dd < max_dd_pct:
            max_dd_pct = dd
            dd_peak_close = peak_close
            dd_peak_date = peak_date
            dd_trough_close = close
            dd_trough_date = bar["date"]

    return {
        "ticker": ticker,
        "max_drawdown_pct": round(max_dd_pct, 6),
        "peak_date": dd_peak_date,
        "trough_date": dd_trough_date,
        "peak_close": dd_peak_close,
        "trough_close": dd_trough_close,
    }


@mcp.tool()
async def price_momentum(
    ticker: str,
    bars: list[dict] | None = None,
    bars_ref: _BarsRef = None,
    window: int = 20,
) -> dict:
    """Return a simple momentum signal: last close vs N-day moving average.

    `bars` may be supplied inline or via `bars_ref` from
    `instruments__get_ohlcv_history`; this tool does not accept date ranges alone.
    signal is "above_ma", "below_ma", or "insufficient_data".
    """
    _require_bearer()
    bars = await _resolve_bars(bars, bars_ref)
    closes = [float(b["close"]) for b in bars]
    if len(closes) < window:
        return {
            "ticker": ticker,
            "window": window,
            "last_close": closes[-1] if closes else None,
            "moving_avg": None,
            "signal": "insufficient_data",
            "as_of": bars[-1]["date"] if bars else None,
        }
    last_close = closes[-1]
    ma_window = closes[-window:]
    moving_avg = sum(ma_window) / len(ma_window)
    signal = "above_ma" if last_close > moving_avg else "below_ma"
    return {
        "ticker": ticker,
        "window": window,
        "last_close": last_close,
        "moving_avg": round(moving_avg, 6),
        "signal": signal,
        "as_of": bars[-1]["date"],
    }


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
        can_publish=False,
        can_consume=True,
        result_types=("ohlcv_bars",),
    )


@mcp.tool()
def position_market_value(
    client_id: str,
    ticker: str,
    quantity: int,
    spot_price: float,
    currency: str,
) -> dict:
    """Compute market value for one holding using a quantity and spot price supplied by the agent.

    The agent must fetch the holding from Client Service and spot price from Instrument Service.
    """
    _require_bearer()
    return {
        "client_id": client_id,
        "ticker": ticker,
        "quantity": quantity,
        "spot_price": spot_price,
        "currency": currency,
        "market_value": round(quantity * spot_price, 4),
    }


@mcp.tool()
def compare_execution_to_vwap(
    ticker: str,
    side: str,
    execution_price: float,
    vwap_price: float,
) -> dict:
    """Compare an execution price against a VWAP in basis points.

    Favourable means: buy execution below VWAP or sell execution above VWAP.
    basis_points = (execution_price - vwap_price) / vwap_price * 10000
    """
    _require_bearer()
    basis_points = (execution_price - vwap_price) / vwap_price * 10000
    favourable = (side.lower() == "buy" and execution_price < vwap_price) or (
        side.lower() == "sell" and execution_price > vwap_price
    )
    return {
        "ticker": ticker,
        "side": side.lower(),
        "execution_price": execution_price,
        "vwap": vwap_price,
        "basis_points": round(basis_points, 4),
        "favourable": favourable,
    }
