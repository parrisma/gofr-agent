"""Fixture data integrity tests.

Verifies that CSV data is internally consistent before any service is built.
Does not start any MCP servers.
"""

from __future__ import annotations

import csv

from tests.fixtures.mcp_services._data_loader import DATA_DIR, csv_rows, csv_table


def test_every_watchlist_ticker_exists() -> None:
    instruments = csv_table("instruments.csv", "ticker")
    watchlist = csv_rows("watchlist.csv")
    for row in watchlist:
        assert row["ticker"] in instruments, (
            f"watchlist ticker {row['ticker']} not in instruments.csv"
        )


def test_every_trade_reference_exists() -> None:
    instruments = csv_table("instruments.csv", "ticker")
    clients = csv_table("clients.csv", "client_id")
    trades = csv_rows("trades.csv")
    for row in trades:
        assert row["ticker"] in instruments, (
            f"trade {row['trade_id']} ticker {row['ticker']} not in instruments.csv"
        )
        assert row["client_id"] in clients, (
            f"trade {row['trade_id']} client_id {row['client_id']} not in clients.csv"
        )


def test_every_client_has_between_five_and_twenty_trades() -> None:
    clients = csv_table("clients.csv", "client_id")
    trades = csv_rows("trades.csv")
    trade_counts = {client_id: 0 for client_id in clients}
    for row in trades:
        trade_counts[row["client_id"]] += 1

    for client_id, count in trade_counts.items():
        assert 5 <= count <= 20, (
            f"client {client_id} has {count} trades, expected between 5 and 20"
        )


def test_every_client_has_mandate_document() -> None:
    clients = csv_table("clients.csv", "client_id")
    mandates = csv_table("mandates.csv", "client_id")
    assert set(mandates) == set(clients), (
        "mandates.csv client coverage does not match clients.csv: "
        f"missing={sorted(set(clients) - set(mandates))}, "
        f"extra={sorted(set(mandates) - set(clients))}"
    )


def test_every_trade_price_inside_ohlcv_band() -> None:
    trades = csv_rows("trades.csv")
    instruments = csv_table("instruments.csv", "ticker")
    ohlcv_dir = DATA_DIR / "ohlcv"
    # Load all OHLCV bars into a dict keyed by (ticker, date)
    bars: dict[tuple[str, str], dict] = {}
    for p in ohlcv_dir.glob("*.csv"):
        with p.open(newline="", encoding="utf-8") as fh:
            for bar in csv.DictReader(fh):
                bars[(p.stem, bar["date"])] = bar
    for row in trades:
        key = (row["ticker"], row["trade_date"])
        assert key in bars, (
            f"trade {row['trade_id']} date {row['trade_date']} has no OHLCV bar for {row['ticker']}"
        )
        assert row["currency"] == instruments[row["ticker"]]["currency"], (
            f"trade {row['trade_id']} currency {row['currency']!r} does not match "
            f"instrument currency {instruments[row['ticker']]['currency']!r}"
        )
        bar = bars[key]
        price = float(row["price"])
        low = float(bar["low"])
        high = float(bar["high"])
        assert low <= price <= high, (
            f"trade {row['trade_id']} price {price} outside OHLCV band [{low}, {high}] "
            f"for {row['ticker']} on {row['trade_date']}"
        )


def test_spot_prices_reference_known_instruments() -> None:
    instruments = csv_table("instruments.csv", "ticker")
    spot = csv_rows("spot_prices.csv")
    spot_tickers = {row["ticker"] for row in spot}
    for row in spot:
        assert row["ticker"] in instruments, (
            f"spot_prices.csv ticker {row['ticker']} not in instruments.csv"
        )
        assert row["currency"] == instruments[row["ticker"]]["currency"], (
            f"spot_prices.csv currency for {row['ticker']} is {row['currency']!r}, "
            f"expected {instruments[row['ticker']]['currency']!r}"
        )
        assert row["as_of"] == "2026-05-13", (
            f"spot_prices.csv as_of date for {row['ticker']} is "
            f"{row['as_of']!r}, expected 2026-05-13"
        )
    assert spot_tickers == set(instruments), (
        "spot_prices.csv ticker coverage does not match instruments.csv: "
        f"missing={sorted(set(instruments) - spot_tickers)}, "
        f"extra={sorted(spot_tickers - set(instruments))}"
    )


def test_every_ohlcv_file_has_90_rows_and_latest_date() -> None:
    instruments = csv_table("instruments.csv", "ticker")
    ohlcv_dir = DATA_DIR / "ohlcv"
    files = list(ohlcv_dir.glob("*.csv"))
    file_stems = {p.stem for p in files}
    assert file_stems == set(instruments), (
        "ohlcv file coverage does not match instruments.csv: "
        f"missing={sorted(set(instruments) - file_stems)}, "
        f"extra={sorted(file_stems - set(instruments))}"
    )
    for p in files:
        with p.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 90, (
            f"{p.name} has {len(rows)} rows, expected 90"
        )
        assert rows[-1]["date"] == "2026-05-13", (
            f"{p.name} last date is {rows[-1]['date']!r}, expected 2026-05-13"
        )
