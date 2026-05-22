"""Integration tests for the Client test MCP service."""

from __future__ import annotations

import json

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from tests.fixtures.mcp_services._data_loader import csv_rows
from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helper (same pattern as test_instruments_service.py)
# ---------------------------------------------------------------------------


def _parse_item(text: str) -> object:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _expected_holdings(client_id: str) -> list[dict[str, int | str]]:
    positions: dict[str, int] = {}
    for row in csv_rows("trades.csv"):
        if row["client_id"] != client_id:
            continue
        quantity = int(row["quantity"])
        if row["side"] == "sell":
            quantity *= -1
        positions[row["ticker"]] = positions.get(row["ticker"], 0) + quantity
    return [
        {"client_id": client_id, "ticker": ticker, "quantity": quantity}
        for ticker, quantity in sorted(positions.items())
        if quantity != 0
    ]


def _expected_holders(ticker: str) -> list[str]:
    positions: dict[str, int] = {}
    for row in csv_rows("trades.csv"):
        if row["ticker"] != ticker:
            continue
        quantity = int(row["quantity"])
        if row["side"] == "sell":
            quantity *= -1
        positions[row["client_id"]] = positions.get(row["client_id"], 0) + quantity
    return sorted(client_id for client_id, quantity in positions.items() if quantity != 0)


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


async def test_client_lookup_no_token_raises(clients_url: str) -> None:
    """Calling any tool without a bearer token must produce an error."""
    async with (
        streamablehttp_client(clients_url, headers={}) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool("client_lookup", arguments={"query": "C001"})
    assert result.isError or len(result.content) > 0
    if result.content:
        text = result.content[0].text.lower()
        assert "authorization" in text or "bearer" in text or "error" in text


# ---------------------------------------------------------------------------
# 2. client_lookup
# ---------------------------------------------------------------------------


async def test_client_lookup_by_id(clients_url: str) -> None:
    result = await _call_json(clients_url, "client_lookup", {"query": "C001"})
    assert result is not None
    assert result["name"] == "Meridian Capital"
    assert "fund_mandate" not in result


async def test_client_lookup_by_name_substring(clients_url: str) -> None:
    result = await _call_json(clients_url, "client_lookup", {"query": "apex"})
    assert result is not None
    assert result["client_id"] == "C002"


async def test_client_lookup_unknown_returns_none(clients_url: str) -> None:
    result = await _call_json(clients_url, "client_lookup", {"query": "ZZZZ"})
    assert result is None


# ---------------------------------------------------------------------------
# 3. list_clients
# ---------------------------------------------------------------------------


async def test_list_clients_returns_three(clients_url: str) -> None:
    result = await _call_json(clients_url, "list_clients", {})
    assert isinstance(result, list)
    assert len(result) == 23
    ids = {r["client_id"] for r in result}
    assert ids == {f"C{i:03d}" for i in range(1, 24)}
    assert all("fund_mandate" not in row for row in result)


# ---------------------------------------------------------------------------
# 4. get_holdings
# ---------------------------------------------------------------------------


async def test_get_holdings_c001(clients_url: str) -> None:
    result = await _call_json(clients_url, "get_holdings", {"client_id": "C001"})
    assert isinstance(result, list)
    assert result == _expected_holdings("C001")


async def test_get_holdings_unknown_returns_empty(clients_url: str) -> None:
    result = await _call_json(clients_url, "get_holdings", {"client_id": "ZZZZ"})
    assert result is None or result == []


async def test_get_holdings_short_position(clients_url: str) -> None:
    result = await _call_json(clients_url, "get_holdings", {"client_id": "C002"})
    assert isinstance(result, list)
    assert result == _expected_holdings("C002")
    tsla = next((r for r in result if r["ticker"] == "TSLA"), None)
    assert tsla is not None
    assert tsla["quantity"] == -500


# ---------------------------------------------------------------------------
# 5. get_holding
# ---------------------------------------------------------------------------


async def test_get_holding_found(clients_url: str) -> None:
    result = await _call_json(clients_url, "get_holding", {"client_id": "C001", "ticker": "BARC"})
    assert result == next(r for r in _expected_holdings("C001") if r["ticker"] == "BARC")


async def test_get_holding_not_held(clients_url: str) -> None:
    # C001 does not hold NVDA in the holdings snapshot
    result = await _call_json(clients_url, "get_holding", {"client_id": "C001", "ticker": "NVDA"})
    assert result is None


# ---------------------------------------------------------------------------
# 6. list_portfolio_tickers
# ---------------------------------------------------------------------------


async def test_list_portfolio_tickers_c001(clients_url: str) -> None:
    result = await _call_json(clients_url, "list_portfolio_tickers", {"client_id": "C001"})
    assert isinstance(result, list)
    assert result == [holding["ticker"] for holding in _expected_holdings("C001")]


# ---------------------------------------------------------------------------
# 7. get_watchlist
# ---------------------------------------------------------------------------


async def test_get_watchlist_c001(clients_url: str) -> None:
    result = await _call_json(clients_url, "get_watchlist", {"client_id": "C001"})
    assert isinstance(result, list)
    assert "NVDA" in result
    assert "TSLA" in result


async def test_get_watchlist_unknown_returns_empty(clients_url: str) -> None:
    result = await _call_json(clients_url, "get_watchlist", {"client_id": "ZZZZ"})
    assert result is None or result == []


# ---------------------------------------------------------------------------
# 8. is_on_watchlist
# ---------------------------------------------------------------------------


async def test_is_on_watchlist_true(clients_url: str) -> None:
    result = await _call_json(
        clients_url, "is_on_watchlist", {"client_id": "C003", "ticker": "TSLA"}
    )
    assert result is not None
    assert result["is_watched"] is True


async def test_is_on_watchlist_false(clients_url: str) -> None:
    # C001 holds BARC but does not watch it
    result = await _call_json(
        clients_url, "is_on_watchlist", {"client_id": "C001", "ticker": "BARC"}
    )
    assert result is not None
    assert result["is_watched"] is False


# ---------------------------------------------------------------------------
# 9. get_mandate_document
# ---------------------------------------------------------------------------


async def test_get_mandate_document_returns_text(clients_url: str) -> None:
    result = await _call_json(clients_url, "get_mandate_document", {"client_id": "C001"})
    assert result is not None
    assert result["fund_mandate"] == "Long-only US and UK listed equities"
    assert "long-only" in result["mandate_text"].lower()
    assert result["mandate_version"] == "v1"


async def test_get_mandate_document_expanded_client_returns_text(clients_url: str) -> None:
    result = await _call_json(clients_url, "get_mandate_document", {"client_id": "C022"})
    assert result is not None
    assert result["fund_mandate"] == "Spot crypto ETF allocation"
    assert "stable coins" in result["mandate_text"].lower()
    assert result["mandate_version"] == "v1"


async def test_get_mandate_document_unknown_returns_none(clients_url: str) -> None:
    result = await _call_json(clients_url, "get_mandate_document", {"client_id": "ZZZZ"})
    assert result is None


# ---------------------------------------------------------------------------
# 10. search_mandate_text
# ---------------------------------------------------------------------------


async def test_search_mandate_text_finds_short_term(clients_url: str) -> None:
    result = await _call_json(
        clients_url,
        "search_mandate_text",
        {"client_id": "C002", "query_terms": ["short"]},
    )
    assert isinstance(result, list)
    assert len(result) > 0
    assert any("short" in ex["excerpt"].lower() for ex in result)


async def test_search_mandate_text_esg(clients_url: str) -> None:
    result = await _call_json(
        clients_url,
        "search_mandate_text",
        {"client_id": "C003", "query_terms": ["ESG", "exclusion"]},
    )
    assert isinstance(result, list)
    assert len(result) > 0
    matched_terms_flat = [t for ex in result for t in ex["matched_terms"]]
    assert any(t.lower() in ("esg", "exclusion") for t in matched_terms_flat)


async def test_search_mandate_text_no_match_returns_empty(clients_url: str) -> None:
    result = await _call_json(
        clients_url,
        "search_mandate_text",
        {"client_id": "C001", "query_terms": ["commodities"]},
    )
    assert result is None or result == []


# ---------------------------------------------------------------------------
# 11. list_mandate_documents
# ---------------------------------------------------------------------------


async def test_list_mandate_documents_count(clients_url: str) -> None:
    result = await _call_json(clients_url, "list_mandate_documents", {})
    assert isinstance(result, list)
    assert len(result) == 23
    for row in result:
        assert "mandate_text" not in row
        assert "client_id" in row
        assert "fund_mandate" in row
        assert "mandate_version" in row
        assert "effective_date" in row
    ids = {row["client_id"] for row in result}
    assert ids == {f"C{i:03d}" for i in range(1, 24)}
    c001 = next(row for row in result if row["client_id"] == "C001")
    assert c001["fund_mandate"] == "Long-only US and UK listed equities"


# ---------------------------------------------------------------------------
# 12. Inverse lookups
# ---------------------------------------------------------------------------


async def test_get_clients_holding_aapl(clients_url: str) -> None:
    result = await _call_json(clients_url, "get_clients_holding", {"ticker": "AAPL"})
    assert isinstance(result, list)
    assert result == _expected_holders("AAPL")


async def test_get_clients_watching_nvda(clients_url: str) -> None:
    result = await _call_json(clients_url, "get_clients_watching", {"ticker": "NVDA"})
    assert isinstance(result, list)
    assert "C001" in result
    assert "C003" in result


async def test_get_clients_holding_not_held(clients_url: str) -> None:
    result = await _call_json(clients_url, "get_clients_holding", {"ticker": "ZZZZ"})
    assert result is None or result == []
