"""Fixture data integrity tests.

Verifies that CSV data is internally consistent before any service is built.
Does not start any MCP servers.
"""

from __future__ import annotations

import csv

from tests.fixtures.mcp_services._data_loader import DATA_DIR, csv_rows, csv_table


def test_every_holding_ticker_exists() -> None:
    instruments = csv_table("instruments.csv", "ticker")
    holdings = csv_rows("holdings.csv")
    for row in holdings:
        assert row["ticker"] in instruments, (
            f"holding ticker {row['ticker']} not in instruments.csv"
        )


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


def test_every_trade_price_inside_ohlcv_band() -> None:
    trades = csv_rows("trades.csv")
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
    for row in spot:
        assert row["ticker"] in instruments, (
            f"spot_prices.csv ticker {row['ticker']} not in instruments.csv"
        )
        assert row["as_of"] == "2026-05-13", (
            f"spot_prices.csv as_of date for {row['ticker']} is "
            f"{row['as_of']!r}, expected 2026-05-13"
        )


def test_every_ohlcv_file_has_90_rows_and_latest_date() -> None:
    ohlcv_dir = DATA_DIR / "ohlcv"
    files = list(ohlcv_dir.glob("*.csv"))
    assert len(files) == 6, f"Expected 6 OHLCV files, found {len(files)}"
    for p in files:
        with p.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 90, (
            f"{p.name} has {len(rows)} rows, expected 90"
        )
        assert rows[-1]["date"] == "2026-05-13", (
            f"{p.name} last date is {rows[-1]['date']!r}, expected 2026-05-13"
        )
