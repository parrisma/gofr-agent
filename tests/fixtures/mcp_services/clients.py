"""Client master test MCP service.

Provides 12 tools covering client identity, holdings, watchlists, and mandates.
All tools call _require_bearer() first; any non-empty bearer token is accepted.
"""

from __future__ import annotations

from collections import defaultdict

from mcp.server.fastmcp import FastMCP

from tests.fixtures.mcp_services._data_loader import csv_rows, csv_table
from tests.fixtures.mcp_services._server import _require_bearer

# ---------------------------------------------------------------------------
# Module-level data (loaded once at import)
# ---------------------------------------------------------------------------

_CLIENTS: dict[str, dict] = csv_table("clients.csv", "client_id")
_MANDATES: dict[str, dict] = csv_table("mandates.csv", "client_id")
_TRADES_RAW = csv_rows("trades.csv")

_WATCHLIST_RAW = csv_rows("watchlist.csv")

_WATCHLIST: dict[str, list[str]] = defaultdict(list)
for _row in _WATCHLIST_RAW:
    _WATCHLIST[_row["client_id"]].append(_row["ticker"])

_TICKER_TO_WATCHERS: dict[str, list[str]] = defaultdict(list)
for _row in _WATCHLIST_RAW:
    _TICKER_TO_WATCHERS[_row["ticker"]].append(_row["client_id"])

# ---------------------------------------------------------------------------
# FastMCP instance
# ---------------------------------------------------------------------------

mcp = FastMCP("clients-test-service")


def _client_record(row: dict[str, str]) -> dict[str, str]:
    return {
        "client_id": row["client_id"],
        "name": row["name"],
    }


def _position_quantities() -> dict[tuple[str, str], int]:
    positions: dict[tuple[str, str], int] = defaultdict(int)
    for row in _TRADES_RAW:
        quantity = int(row["quantity"])
        if row["side"] == "sell":
            quantity *= -1
        positions[(row["client_id"], row["ticker"])] += quantity
    return positions


def _holdings_for_client(client_id: str) -> list[dict[str, int | str]]:
    holdings: list[dict[str, int | str]] = []
    for (current_client_id, ticker), quantity in sorted(_position_quantities().items()):
        if current_client_id != client_id or quantity == 0:
            continue
        holdings.append({
            "client_id": client_id,
            "ticker": ticker,
            "quantity": quantity,
        })
    return holdings


def _holding_for_client_ticker(client_id: str, ticker: str) -> dict[str, int | str] | None:
    quantity = _position_quantities().get((client_id, ticker.upper()), 0)
    if quantity == 0:
        return None
    return {
        "client_id": client_id,
        "ticker": ticker.upper(),
        "quantity": quantity,
    }


def _clients_holding_ticker(ticker: str) -> list[str]:
    holders = [
        client_id
        for (client_id, current_ticker), quantity in _position_quantities().items()
        if current_ticker == ticker.upper() and quantity != 0
    ]
    return sorted(holders)

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def client_lookup(query: str) -> dict | None:
    """Resolve a client ID or name substring to a canonical client record.

    Exact client_id match is tried first, then case-insensitive name substring.
    Returns None when no match is found.
    """
    _require_bearer()
    # Exact client_id match
    if query.upper() in _CLIENTS:
        row = _CLIENTS[query.upper()]
        return _client_record(row)
    # Case-insensitive name substring
    q = query.lower()
    for row in _CLIENTS.values():
        if q in row["name"].lower():
            return _client_record(row)
    return None


@mcp.tool()
def list_clients() -> list[dict]:
    """Return all client records."""
    _require_bearer()
    return [_client_record(row) for row in _CLIENTS.values()]


@mcp.tool()
def get_holdings(client_id: str) -> list[dict]:
    """Return the current holdings snapshot for a client.

    Returns an empty list for unknown client IDs.
    """
    _require_bearer()
    return _holdings_for_client(client_id)


@mcp.tool()
def get_holding(client_id: str, ticker: str) -> dict | None:
    """Return one client's holding in one instrument.

    Returns None if the client has no current position in the ticker.
    """
    _require_bearer()
    return _holding_for_client_ticker(client_id, ticker)


@mcp.tool()
def list_portfolio_tickers(client_id: str) -> list[str]:
    """Return distinct tickers currently held by a client."""
    _require_bearer()
    return [holding["ticker"] for holding in _holdings_for_client(client_id)]


@mcp.tool()
def get_watchlist(client_id: str) -> list[str]:
    """Return the tickers on a client's watchlist.

    Returns an empty list for unknown client IDs.
    """
    _require_bearer()
    return list(_WATCHLIST.get(client_id, []))


@mcp.tool()
def is_on_watchlist(client_id: str, ticker: str) -> dict:
    """Return whether one instrument is on a client's watchlist."""
    _require_bearer()
    watched = ticker.upper() in _WATCHLIST.get(client_id, [])
    return {"client_id": client_id, "ticker": ticker.upper(), "is_watched": watched}


@mcp.tool()
def get_mandate_document(client_id: str) -> dict | None:
    """Return the written trading mandate for a client.

    Returns None for unknown client IDs.
    """
    _require_bearer()
    row = _MANDATES.get(client_id)
    if row is None:
        return None
    return {
        "client_id": row["client_id"],
        "fund_mandate": row["fund_mandate"],
        "mandate_version": row["mandate_version"],
        "effective_date": row["effective_date"],
        "mandate_text": row["mandate_text"],
    }


@mcp.tool()
def search_mandate_text(client_id: str, query_terms: list[str]) -> list[dict]:
    """Return mandate text excerpts containing one or more query terms (lexical match).

    Splits the mandate text into sentences and returns sentences that contain any term.
    Returns an empty list when there is no match or the client is unknown.
    """
    _require_bearer()
    row = _MANDATES.get(client_id)
    if row is None:
        return []
    text = row["mandate_text"]
    # Split on ". " to produce rough sentences
    sentences = [s.strip() for s in text.replace(".\n", ". ").split(". ") if s.strip()]
    excerpts: list[dict] = []
    for sentence in sentences:
        sentence_lower = sentence.lower()
        matched = [t for t in query_terms if t.lower() in sentence_lower]
        if matched:
            excerpts.append({
                "client_id": client_id,
                "mandate_version": row["mandate_version"],
                "excerpt": sentence,
                "matched_terms": matched,
            })
    return excerpts


@mcp.tool()
def list_mandate_documents() -> list[dict]:
    """Return metadata for all available mandate documents (no mandate text)."""
    _require_bearer()
    return [
        {
            "client_id": r["client_id"],
            "fund_mandate": r["fund_mandate"],
            "mandate_version": r["mandate_version"],
            "effective_date": r["effective_date"],
        }
        for r in _MANDATES.values()
    ]


@mcp.tool()
def get_clients_holding(ticker: str) -> list[str]:
    """Return all client IDs that hold a given ticker (long or short)."""
    _require_bearer()
    return _clients_holding_ticker(ticker)


@mcp.tool()
def get_clients_watching(ticker: str) -> list[str]:
    """Return all client IDs that have a given ticker on their watchlist."""
    _require_bearer()
    return list(_TICKER_TO_WATCHERS.get(ticker.upper(), []))
