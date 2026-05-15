"""Trade blotter test MCP service.

Provides 9 tools covering trade retrieval, aggregation, and FIFO P&L.
All tools call _require_bearer() first; any non-empty bearer token is accepted.
"""

from __future__ import annotations

from collections import defaultdict

from mcp.server.fastmcp import FastMCP

from tests.fixtures.mcp_services._data_loader import csv_rows
from tests.fixtures.mcp_services._server import _require_bearer

# ---------------------------------------------------------------------------
# Module-level data (loaded once at import)
# ---------------------------------------------------------------------------

_ALL_TRADES: list[dict] = csv_rows("trades.csv")

_BY_CLIENT: dict[str, list[dict]] = defaultdict(list)
_BY_TICKER: dict[str, list[dict]] = defaultdict(list)
_BY_TRADE_ID: dict[str, dict] = {}
_BY_CLIENT_TICKER: dict[tuple, list[dict]] = defaultdict(list)

for _row in _ALL_TRADES:
    _BY_CLIENT[_row["client_id"]].append(_row)
    _BY_TICKER[_row["ticker"]].append(_row)
    _BY_TRADE_ID[_row["trade_id"]] = _row
    _BY_CLIENT_TICKER[(_row["client_id"], _row["ticker"])].append(_row)


def _trade_dict(row: dict) -> dict:
    return {
        "trade_id": row["trade_id"],
        "client_id": row["client_id"],
        "ticker": row["ticker"],
        "side": row["side"],
        "quantity": int(row["quantity"]),
        "price": float(row["price"]),
        "currency": row["currency"],
        "trade_date": row["trade_date"],
    }


# ---------------------------------------------------------------------------
# FastMCP instance
# ---------------------------------------------------------------------------

mcp = FastMCP("trades-test-service")

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_trades(
    client_id: str | None = None,
    ticker: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[dict]:
    """Return trades filtered by client, instrument, and/or date range.

    All parameters are optional; omitting all returns the full blotter.
    """
    _require_bearer()
    rows = list(_ALL_TRADES)
    if client_id is not None:
        rows = [r for r in rows if r["client_id"] == client_id]
    if ticker is not None:
        rows = [r for r in rows if r["ticker"] == ticker.upper()]
    if from_date is not None:
        rows = [r for r in rows if r["trade_date"] >= from_date]
    if to_date is not None:
        rows = [r for r in rows if r["trade_date"] <= to_date]
    return [_trade_dict(r) for r in rows]


@mcp.tool()
def get_trade(trade_id: str) -> dict | None:
    """Return a single trade record by trade ID. Returns None for unknown IDs."""
    _require_bearer()
    row = _BY_TRADE_ID.get(trade_id)
    return _trade_dict(row) if row is not None else None


@mcp.tool()
def get_last_trade(client_id: str, ticker: str) -> dict | None:
    """Return the most recent trade for a client/instrument pair.

    Returns None if no trades exist for this pair.
    """
    _require_bearer()
    rows = _BY_CLIENT_TICKER.get((client_id, ticker.upper()), [])
    if not rows:
        return None
    latest = max(rows, key=lambda r: r["trade_date"])
    return _trade_dict(latest)


@mcp.tool()
def list_clients_traded_instrument(
    ticker: str,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[str]:
    """Return distinct client IDs that traded a ticker in an optional date range."""
    _require_bearer()
    rows = list(_BY_TICKER.get(ticker.upper(), []))
    if from_date is not None:
        rows = [r for r in rows if r["trade_date"] >= from_date]
    if to_date is not None:
        rows = [r for r in rows if r["trade_date"] <= to_date]
    return sorted(set(r["client_id"] for r in rows))


@mcp.tool()
def get_trade_activity_window(client_id: str, from_date: str, to_date: str) -> list[dict]:
    """Return a compact activity summary per ticker for one client over a date range."""
    _require_bearer()
    rows = [
        r for r in _BY_CLIENT.get(client_id, [])
        if from_date <= r["trade_date"] <= to_date
    ]
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_ticker[r["ticker"]].append(r)
    result = []
    for tkr, tkr_rows in sorted(by_ticker.items()):
        buys = [r for r in tkr_rows if r["side"] == "buy"]
        sells = [r for r in tkr_rows if r["side"] == "sell"]
        gross_qty = sum(int(r["quantity"]) for r in tkr_rows)
        net_qty = sum(int(r["quantity"]) for r in buys) - sum(int(r["quantity"]) for r in sells)
        result.append({
            "client_id": client_id,
            "ticker": tkr,
            "trade_count": len(tkr_rows),
            "gross_quantity": gross_qty,
            "net_quantity": net_qty,
        })
    return result


@mcp.tool()
def get_trade_summary(client_id: str, ticker: str) -> dict:
    """Return aggregated buy/sell counts and net quantity for a client/instrument pair."""
    _require_bearer()
    rows = _BY_CLIENT_TICKER.get((client_id, ticker.upper()), [])
    buys = [r for r in rows if r["side"] == "buy"]
    sells = [r for r in rows if r["side"] == "sell"]

    def _wavg(rs: list[dict]) -> float | None:
        if not rs:
            return None
        total_qty = sum(int(r["quantity"]) for r in rs)
        if total_qty == 0:
            return None
        return sum(float(r["price"]) * int(r["quantity"]) for r in rs) / total_qty

    net_qty = sum(int(r["quantity"]) for r in buys) - sum(int(r["quantity"]) for r in sells)
    return {
        "client_id": client_id,
        "ticker": ticker.upper(),
        "total_buys": len(buys),
        "total_sells": len(sells),
        "net_quantity": net_qty,
        "avg_buy_price": _wavg(buys),
        "avg_sell_price": _wavg(sells),
    }


@mcp.tool()
def get_average_execution_price(
    client_id: str,
    ticker: str,
    side: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """Return side-specific average execution price for a client/instrument pair."""
    _require_bearer()
    rows = list(_BY_CLIENT_TICKER.get((client_id, ticker.upper()), []))
    if side is not None:
        rows = [r for r in rows if r["side"] == side.lower()]
    if from_date is not None:
        rows = [r for r in rows if r["trade_date"] >= from_date]
    if to_date is not None:
        rows = [r for r in rows if r["trade_date"] <= to_date]

    total_qty = sum(int(r["quantity"]) for r in rows)
    currency = rows[0]["currency"] if rows else None

    avg_price: float | None = None
    if total_qty > 0:
        avg_price = sum(float(r["price"]) * int(r["quantity"]) for r in rows) / total_qty

    return {
        "client_id": client_id,
        "ticker": ticker.upper(),
        "side": side,
        "avg_price": avg_price,
        "total_quantity": total_qty,
        "trade_count": len(rows),
        "currency": currency,
    }


@mcp.tool()
def get_realised_pnl(client_id: str, ticker: str) -> dict:
    """Compute FIFO realised P&L for a client's round-trip trades in an instrument.

    Returns realised_pnl=0.0 and matched_trades=0 if no round trips exist.
    """
    _require_bearer()
    rows = sorted(
        _BY_CLIENT_TICKER.get((client_id, ticker.upper()), []),
        key=lambda r: r["trade_date"],
    )
    currency = rows[0]["currency"] if rows else "USD"
    buys = [(int(r["quantity"]), float(r["price"])) for r in rows if r["side"] == "buy"]
    sells = [r for r in rows if r["side"] == "sell"]

    buy_queue = list(buys)
    realised_pnl = 0.0
    matched_trades = 0

    for sell in sells:
        remaining = int(sell["quantity"])
        sell_price = float(sell["price"])
        while remaining > 0 and buy_queue:
            bq, bp = buy_queue.pop(0)
            matched = min(bq, remaining)
            realised_pnl += matched * (sell_price - bp)
            if bq > matched:
                buy_queue.insert(0, (bq - matched, bp))
            remaining -= matched
            matched_trades += 1

    return {
        "client_id": client_id,
        "ticker": ticker.upper(),
        "currency": currency,
        "realised_pnl": round(realised_pnl, 4),
        "matched_trades": matched_trades,
    }


@mcp.tool()
def list_traded_instruments(client_id: str) -> list[str]:
    """Return the distinct tickers that a client has traded."""
    _require_bearer()
    return sorted(set(r["ticker"] for r in _BY_CLIENT.get(client_id, [])))
