"""Generate synthetic OHLCV CSVs for each ticker.

Run once:  uv run python scripts/generate_ohlcv.py
Commit the resulting data/ohlcv/*.csv files.
"""

import csv
import random
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

TICKERS = {
    "AAPL": (190.0, 2_000_000),
    "MSFT": (415.0, 1_500_000),
    "NVDA": (875.0, 3_000_000),
    "TSLA": (175.0, 4_000_000),
    "BARC": (2.15, 5_000_000),
    "VOD":  (0.72, 8_000_000),
}

OUT_DIR = Path(__file__).parent.parent / "tests/fixtures/mcp_services/data/ohlcv"
OUT_DIR.mkdir(parents=True, exist_ok=True)
TRADES_CSV = Path(__file__).parent.parent / "tests/fixtures/mcp_services/data/trades.csv"

END_DATE = date(2026, 5, 13)


def trade_prices_by_ticker_date() -> dict[tuple[str, str], list[float]]:
    """Load trade prices so generated high/low bands contain every execution."""
    result: dict[tuple[str, str], list[float]] = defaultdict(list)
    with TRADES_CSV.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            result[(row["ticker"], row["trade_date"])].append(float(row["price"]))
    return result


def trading_days(end: date, n: int) -> list[date]:
    days, d = [], end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return list(reversed(days))


trade_prices = trade_prices_by_ticker_date()

for ticker, (start_price, base_vol) in TICKERS.items():
    rng = random.Random(ticker)      # deterministic per ticker
    dates = trading_days(END_DATE, 90)
    rows = []
    close = start_price
    for d in dates:
        change = rng.uniform(-0.02, 0.02)
        open_ = round(close * (1 + rng.uniform(-0.005, 0.005)), 4)
        new_close = round(close * (1 + change), 4)
        high = round(max(open_, new_close) * (1 + rng.uniform(0.001, 0.01)), 4)
        low = round(min(open_, new_close) * (1 - rng.uniform(0.001, 0.01)), 4)
        executions = trade_prices.get((ticker, d.isoformat()), [])
        if executions:
            high = round(max(high, max(executions) * 1.001), 4)
            low = round(min(low, min(executions) * 0.999), 4)
        close = new_close
        volume = rng.randint(int(base_vol * 0.7), int(base_vol * 1.3))
        rows.append({"date": d.isoformat(), "open": open_, "high": high,
                     "low": low, "close": close, "volume": volume})
    path = OUT_DIR / f"{ticker}.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["date", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Written {path}")
