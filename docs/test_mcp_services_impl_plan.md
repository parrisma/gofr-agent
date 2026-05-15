# Test MCP Services — Implementation Plan

> **Status:** Draft v0.2  
> **Date:** 2026-05-13  
> **Companion spec:** `docs/test_mcp_services_spec.md`  
> **Scope:** Step-by-step implementation guide for the four in-process test MCP services and their tests. Services are built and tested in order; each phase produces a green test run before the next phase begins.

---

## Prerequisites and Conventions

### Peer Review Findings Applied

This revision fixes several implementation hazards from the first draft:

- Pytest fixtures for these integration tests must live in `tests/integration/conftest.py`, not under `tests/fixtures/`, because sibling conftest files are not discovered.
- Service fixtures should be requested explicitly rather than `autouse=True`, so each service can be implemented and tested one at a time without importing unfinished modules.
- Auth extraction should use the existing `AuthHeaderMiddleware` + `get_auth_header_from_context()` pattern already proven by the auth-header integration spike.
- Tool signatures should expose only business parameters. Auth/context plumbing must not appear in the MCP tool schema shown to the agent.
- CSV data consistency needs its own pre-service test gate, especially to guarantee that hard-coded trade prices sit inside generated OHLCV high-low bands.

### Shared conventions

All four services follow the same conventions established by `tests/integration/mock_mcp_server.py`. Before writing any service code, read that file in full.

- **FastMCP** is used for every service.  
- **`_UvicornThread`** is copy-shared as a utility (once) in `tests/fixtures/mcp_services/_server.py`.  
- Every service app is wrapped in `gofr_common.web.AuthHeaderMiddleware`, matching the existing auth-header spike tests.  
- Every tool handler calls `_require_bearer()` before doing any work.  
- Data is loaded from CSV files at **module import time** into module-level dicts and lists.  
- The `data/` directory contains the authoritative CSVs; editing them requires no Python changes.
- Tool responses normalise CSV strings into JSON-native types before returning: prices/returns are `float`, quantities/volumes/counts are `int`, flags are `bool`, and missing optional scalar values are `None`.

### Response Normalisation Helpers

Each service can keep local helper functions such as `_as_float(row, key)`, `_as_int(row, key)`, and `_instrument_record(row)` rather than returning raw CSV rows. This is especially important for tests like `price == 875.20`, `quantity == -1000`, and analytics calls that receive numeric bars. CSV rows should be treated as storage records; MCP responses should be API records.

### File tree that will exist after all four phases

```
tests/
  fixtures/
    __init__.py
    mcp_services/
      __init__.py
      _server.py          # _UvicornThread, _free_port, _require_bearer
      _data_loader.py     # csv_table(), csv_rows(), DATA_DIR constant
      instruments.py      # phase 1
      clients.py          # phase 2
      trades.py           # phase 3
      analytics.py        # phase 4
      data/
        instruments.csv
        spot_prices.csv
        clients.csv
        mandates.csv
        holdings.csv
        watchlist.csv
        trades.csv
        ohlcv/
          AAPL.csv
          MSFT.csv
          NVDA.csv
          TSLA.csv
          BARC.csv
          VOD.csv
  integration/
    conftest.py                    # existing file; extended incrementally with service fixtures
    test_instruments_service.py   # phase 1
    test_clients_service.py       # phase 2
    test_trades_service.py        # phase 3
    test_analytics_service.py     # phase 4
```

### Auth pattern used in every tool

Every test MCP service is wrapped with `AuthHeaderMiddleware`, and every tool handler calls a shared `_require_bearer()` helper. This mirrors the proven pattern in `tests/integration/test_auth_header_extraction.py`: the HTTP header is stored by middleware and retrieved inside the tool handler through `get_auth_header_from_context()`.

```python
from gofr_common.web import get_auth_header_from_context

def _require_bearer() -> str:
    """Extract bearer token; raise an MCP tool error if absent or empty."""
    auth = get_auth_header_from_context()
    if not auth.lower().startswith("bearer "):
        raise ValueError("Missing or malformed Authorization header")
    token = auth[len("bearer "):].strip()
    if not token:
        raise ValueError("Empty bearer token")
    return token
```

> **Note:** `ValueError` raised inside a FastMCP tool propagates as an MCP error response. Tests assert this by checking the error text. We do not need real JWT validation for these fixtures; any non-empty bearer token is accepted.

### Test pattern used in every test file

Tests call tools via a real MCP `ClientSession` (same as `test_mcp_server_integration.py`) using `streamablehttp_client`. The session-scoped fixture starts the server; individual tests obtain the URL from the fixture.

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

TEST_JWT = "test-token-gofr-fixtures"
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_JWT}"}

async def call(url: str, tool: str, args: dict) -> dict:
    async with streamablehttp_client(url, headers=AUTH_HEADERS) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = await session.call_tool(tool, args)
            import json
            return json.loads(result.content[0].text)
```

---

## Phase 0 — Shared Infrastructure

**Goal:** Create the shared helpers, CSV data files, and data-integrity tests. No service logic yet. After this phase the fixture data can be inspected, all shared helpers import cleanly, and the CSV integrity gate passes.

### Step 0.1 — Directory skeleton

Create the package marker files and OHLCV directory placeholder:

- `tests/fixtures/__init__.py`
- `tests/fixtures/mcp_services/__init__.py`
- `tests/fixtures/mcp_services/data/ohlcv/.gitkeep`

### Step 0.2 — `_server.py`

Create `tests/fixtures/mcp_services/_server.py`.

**Contents:**

```python
"""Shared server lifecycle utilities for in-process test MCP services."""

from __future__ import annotations

import asyncio
import socket
import threading

import uvicorn
from gofr_common.web import AuthHeaderMiddleware, get_auth_header_from_context


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _require_bearer() -> str:
    """Extract bearer token from the MCP request context.

    Raises ValueError (propagated as MCP error) if the header is absent or empty.
    """
    auth = get_auth_header_from_context()
    if not auth.lower().startswith("bearer "):
        raise ValueError("Missing or malformed Authorization header")
    token = auth[len("bearer "):].strip()
    if not token:
        raise ValueError("Empty bearer token")
    return token


class _UvicornThread(threading.Thread):
    """Run a uvicorn ASGI app in a daemon thread."""

    def __init__(self, app: object, host: str, port: int) -> None:
        super().__init__(daemon=True)
        self.config = uvicorn.Config(app, host=host, port=port, log_level="error")
        self.server = uvicorn.Server(self.config)
        self._ready = threading.Event()
        _orig = self.server.startup

        async def _startup_and_signal(sockets=None) -> None:  # type: ignore[return]
            await _orig(sockets=sockets)
            self._ready.set()

        self.server.startup = _startup_and_signal  # type: ignore[method-assign]

    def run(self) -> None:  # pragma: no cover
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.server.serve())

    def wait_ready(self, timeout: float = 10.0) -> None:
        if not self._ready.wait(timeout):
            raise TimeoutError("Test MCP service did not start in time")

    def shutdown(self) -> None:
        self.server.should_exit = True


def make_service_server(mcp_app) -> tuple[str, int, "_UvicornThread"]:
    """Start a FastMCP app and return (host, port, thread)."""
    host = "127.0.0.1"
    port = _free_port()
    app = AuthHeaderMiddleware(mcp_app.streamable_http_app())
    thread = _UvicornThread(app, host, port)
    thread.start()
    thread.wait_ready()
    return host, port, thread
```

### Step 0.3 — `_data_loader.py`

Create `tests/fixtures/mcp_services/_data_loader.py`.

**Contents:**

```python
"""CSV loading helpers for test MCP service data."""

from __future__ import annotations

import csv
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def csv_rows(filename: str) -> list[dict[str, str]]:
    """Load a CSV file from DATA_DIR and return a list of row dicts."""
    path = DATA_DIR / filename
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def csv_table(filename: str, key_col: str) -> dict[str, dict[str, str]]:
    """Load a CSV and return a dict keyed on key_col for O(1) lookup."""
    rows = csv_rows(filename)
    return {row[key_col]: row for row in rows}
```

### Step 0.4 — CSV data files

Create all CSV files with the exact content below. These are the only authoritative data sources.

**`tests/fixtures/mcp_services/data/instruments.csv`**

```
ticker,isin,exchange,name,currency,bloomberg_code,reuters_ric,sedol
AAPL,US0378331005,XNAS,Apple Inc,USD,AAPL US Equity,AAPL.O,2046251
MSFT,US5949181045,XNAS,Microsoft Corp,USD,MSFT US Equity,MSFT.O,2588173
NVDA,US67066G1040,XNAS,NVIDIA Corp,USD,NVDA US Equity,NVDA.O,2379504
TSLA,US88160R1014,XNAS,Tesla Inc,USD,TSLA US Equity,TSLA.O,B616C79
BARC,GB0031348658,XLON,Barclays PLC,GBP,BARC LN Equity,BARC.L,0798059
VOD,GB00BH4HKS39,XLON,Vodafone Group PLC,GBP,VOD LN Equity,VOD.L,BH4HKS3
```

**`tests/fixtures/mcp_services/data/spot_prices.csv`**

```
ticker,price,currency,as_of
AAPL,189.45,USD,2026-05-13
MSFT,415.30,USD,2026-05-13
NVDA,875.20,USD,2026-05-13
TSLA,172.60,USD,2026-05-13
BARC,2.14,GBP,2026-05-13
VOD,0.71,GBP,2026-05-13
```

**`tests/fixtures/mcp_services/data/clients.csv`**

```
client_id,name
C001,Meridian Capital
C002,Apex Fund
C003,Blue Ridge Partners
```

**`tests/fixtures/mcp_services/data/mandates.csv`**

```
client_id,mandate_version,effective_date,mandate_text
C001,v1,2026-01-01,"Meridian Capital is authorised for long-only trading in listed cash equities on US and UK primary exchanges. The portfolio must not initiate or maintain single-name short positions. Purchases of listed ordinary shares and sales that reduce or close existing long positions are permitted. Trading in derivatives, private securities, crypto assets, or non-US/non-UK venues is outside mandate."
C002,v1,2026-01-01,"Apex Fund may trade long and short positions in listed US cash equities. Short sales are permitted where the issuer's primary listing is a US exchange. The mandate does not permit UK or European listed equities, depositary receipts used as substitutes for restricted venues, derivatives, or unlisted securities."
C003,v1,2026-01-01,"Blue Ridge Partners operates a long-only ESG screened mandate for US listed cash equities. The client may buy or sell listed US ordinary shares to build, reduce, or exit long positions. The client must not establish short exposure. Securities with an internal ESG exclusion flag, non-US primary listings, derivatives, and highly leveraged products are outside mandate."
```

**`tests/fixtures/mcp_services/data/holdings.csv`**

```
client_id,ticker,quantity
C001,AAPL,5000
C001,BARC,12000
C001,VOD,8000
C002,AAPL,3000
C002,NVDA,2000
C002,TSLA,-1000
C003,MSFT,7500
C003,AAPL,4000
```

**`tests/fixtures/mcp_services/data/watchlist.csv`**

```
client_id,ticker
C001,NVDA
C001,TSLA
C002,BARC
C003,NVDA
C003,TSLA
C003,VOD
```

**`tests/fixtures/mcp_services/data/trades.csv`**

```
trade_id,client_id,ticker,side,quantity,price,currency,trade_date
T0001,C001,AAPL,buy,1000,182.10,USD,2026-02-14
T0002,C001,AAPL,sell,500,191.30,USD,2026-03-22
T0003,C001,BARC,buy,5000,2.05,GBP,2026-02-20
T0004,C001,VOD,buy,4000,0.68,GBP,2026-03-01
T0005,C002,AAPL,buy,2000,178.50,USD,2026-02-10
T0006,C002,AAPL,sell,2000,194.20,USD,2026-04-15
T0007,C002,NVDA,buy,1000,820.00,USD,2026-02-18
T0008,C002,NVDA,sell,500,870.00,USD,2026-04-10
T0009,C002,TSLA,sell,1000,165.00,USD,2026-03-05
T0010,C002,TSLA,buy,500,158.00,USD,2026-04-20
T0011,C003,MSFT,buy,3000,398.00,USD,2026-02-12
T0012,C003,MSFT,sell,1000,420.50,USD,2026-04-08
T0013,C003,AAPL,buy,2000,181.00,USD,2026-02-25
T0014,C003,AAPL,sell,1000,195.00,USD,2026-04-30
T0015,C001,NVDA,buy,500,815.00,USD,2026-03-10
T0016,C001,NVDA,sell,500,860.00,USD,2026-04-22
T0017,C002,MSFT,buy,1000,400.00,USD,2026-03-15
T0018,C002,MSFT,sell,1000,418.00,USD,2026-05-01
T0019,C001,TSLA,buy,300,160.00,USD,2026-03-20
T0020,C001,TSLA,sell,300,175.00,USD,2026-05-02
```

**`tests/fixtures/mcp_services/data/ohlcv/`** — one file per ticker containing 90 rows.

Each OHLCV CSV has columns: `date,open,high,low,close,volume`. Prices form a deterministic random walk seeded per ticker. All 90 rows cover the 90 trading days ending 2026-05-13.

> The exact price values are generated once by a helper script (`scripts/generate_ohlcv.py`, phase 0.5). Once generated and committed, the CSV is treated as immutable ground truth and the script is not run again in CI.

### Step 0.5 — OHLCV generation script

Create `scripts/generate_ohlcv.py`. Run once locally and commit the six CSV files. Keep the script in the repo so future data edits can intentionally regenerate the OHLCV files.

```python
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
        open_  = round(close * (1 + rng.uniform(-0.005, 0.005)), 4)
      new_close = round(close * (1 + change), 4)
      high   = round(max(open_, new_close) * (1 + rng.uniform(0.001, 0.01)), 4)
      low    = round(min(open_, new_close) * (1 - rng.uniform(0.001, 0.01)), 4)
      executions = trade_prices.get((ticker, d.isoformat()), [])
      if executions:
        high = round(max(high, max(executions) * 1.001), 4)
        low = round(min(low, min(executions) * 0.999), 4)
      close  = new_close
        volume = rng.randint(int(base_vol * 0.7), int(base_vol * 1.3))
        rows.append({"date": d.isoformat(), "open": open_, "high": high,
                     "low": low, "close": close, "volume": volume})
    path = OUT_DIR / f"{ticker}.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["date","open","high","low","close","volume"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Written {path}")
```

### Step 0.6 — Extend integration `conftest.py` skeleton

Append the shared auth constants to the existing `tests/integration/conftest.py`. Do **not** create `tests/fixtures/mcp_services/conftest.py`; pytest will not discover that sibling file for tests located under `tests/integration/` because it is not in their parent directory chain.

```python
TEST_JWT = "test-token-gofr-fixtures"
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_JWT}"}
```

Each service phase later adds one requested fixture to `tests/integration/conftest.py` (`instruments_url`, `clients_url`, `trades_url`, `analytics_url`). These fixtures are **not autouse**. A service starts only for tests that request its URL, which keeps one-at-a-time implementation safe and avoids importing unfinished service modules.

### Step 0.7 — Verify shared infrastructure

```bash
uv run python -c "
from tests.fixtures.mcp_services._data_loader import csv_rows, csv_table
print(csv_table('instruments.csv', 'ticker').keys())
print(csv_rows('clients.csv'))
"
```

Expected output: six ticker keys, three client rows. **No pytest run yet.**

### Step 0.8 — Add fixture data-integrity tests

Create `tests/integration/test_fixture_data_integrity.py`. These tests do not start any MCP servers; they verify that the CSV universe is internally consistent before any service is built.

Required tests:

```
test_every_holding_ticker_exists
  GIVEN: holdings.csv and instruments.csv
  THEN:  every holding ticker exists in instruments.csv

test_every_watchlist_ticker_exists
  GIVEN: watchlist.csv and instruments.csv
  THEN:  every watchlist ticker exists in instruments.csv

test_every_trade_reference_exists
  GIVEN: trades.csv, clients.csv, instruments.csv
  THEN:  every trade client_id and ticker exists

test_every_trade_price_inside_ohlcv_band
  GIVEN: trades.csv and ohlcv/<ticker>.csv
  THEN:  each trade_date has an OHLCV bar and low <= trade.price <= high

test_spot_prices_reference_known_instruments
  GIVEN: spot_prices.csv and instruments.csv
  THEN:  every spot ticker exists and as_of == "2026-05-13"

test_every_ohlcv_file_has_90_rows_and_latest_date
  GIVEN: ohlcv/*.csv
  THEN:  each file has 90 rows and last row date == "2026-05-13"
```

Run this gate before Phase 1:

```bash
uv run python -m pytest tests/integration/test_fixture_data_integrity.py -v
```

---

## Phase 1 — Instrument Service

**Goal:** Implement `instruments.py`, add its fixture to `conftest.py`, write and pass all instrument service tests.

### Step 1.1 — Implement `instruments.py`

Create `tests/fixtures/mcp_services/instruments.py`.

**Data loaded at import time:**

```python
from tests.fixtures.mcp_services._data_loader import csv_rows, csv_table

_INSTRUMENTS: dict[str, dict] = csv_table("instruments.csv", "ticker")
_SPOT:        dict[str, dict] = csv_table("spot_prices.csv", "ticker")

def _load_ohlcv() -> dict[str, list[dict]]:
    from tests.fixtures.mcp_services._data_loader import DATA_DIR
    import csv
    result = {}
    for p in (DATA_DIR / "ohlcv").glob("*.csv"):
        with p.open() as fh:
            result[p.stem] = list(csv.DictReader(fh))
    return result

_OHLCV: dict[str, list[dict]] = _load_ohlcv()
```

**Tools to implement (in order):**

| Tool | Key logic |
|---|---|
| `instrument_lookup` | Case-insensitive match on ticker, ISIN, name substring |
| `get_spot_price` | Direct lookup in `_SPOT` |
| `get_price_on_date` | Find bar in `_OHLCV[ticker]` by date string |
| `list_instruments` | Filter `_INSTRUMENTS` by `exchange` or return all |
| `get_ohlcv_history` | Filter `_OHLCV[ticker]` by `from_date <= date <= to_date` |
| `get_volume_history` | Same filter but return only `date` + `volume` |
| `get_latest_trading_day` | Last entry in `_OHLCV[ticker]` |
| `get_market_codes` | Return bloomberg, ric, sedol, primary_mic from `_INSTRUMENTS` |
| `validate_market_code` | Check `_INSTRUMENTS[ticker]["exchange"] == exchange` |

Each tool calls `_require_bearer()` first. Tool signatures should contain only the business parameters exposed to the agent; do not expose an auth/context parameter in the MCP schema.

**Example structure:**

```python
from mcp.server.fastmcp import FastMCP
from tests.fixtures.mcp_services._server import _require_bearer

mcp = FastMCP("instruments-test-service")

@mcp.tool()
def instrument_lookup(query: str) -> dict | None:
    """Resolve a ticker, ISIN, or name substring to a canonical instrument record."""
  _require_bearer()
    q = query.lower()
    for row in _INSTRUMENTS.values():
        if q in row["ticker"].lower() or q in row["isin"].lower() or q in row["name"].lower():
            return {
                "ticker": row["ticker"],
                "isin": row["isin"],
                "name": row["name"],
                "exchange": row["exchange"],
                "currency": row["currency"],
            }
    return None
```

### Step 1.2 — Add lifecycle to `tests/integration/conftest.py`

```python
from tests.fixtures.mcp_services._server import make_service_server
from tests.fixtures.mcp_services.instruments import mcp as instruments_mcp

@pytest.fixture(scope="session")
def instruments_url() -> str:
  host, port, thread = make_service_server(instruments_mcp)
  yield f"http://{host}:{port}/mcp"
    thread.shutdown()
    thread.join(timeout=5)
```

### Step 1.3 — Write `tests/integration/test_instruments_service.py`

Test cases in implementation order (write each, run, pass, move to next):

#### 1.3.1 — Auth guard

```
test_instrument_lookup_no_token_raises
  GIVEN: call to instrument_lookup with no Authorization header
  WHEN:  MCP error is returned
  THEN:  error text contains "Authorization" or "bearer"
```

#### 1.3.2 — `instrument_lookup`

```
test_instrument_lookup_by_ticker
  GIVEN: query="AAPL"
  THEN:  isin == "US0378331005", exchange == "XNAS"

test_instrument_lookup_by_isin
  GIVEN: query="GB0031348658"
  THEN:  ticker == "BARC"

test_instrument_lookup_by_name_substring
  GIVEN: query="vodafone"
  THEN:  ticker == "VOD"

test_instrument_lookup_unknown_returns_none
  GIVEN: query="ZZZZ"
  THEN:  result is None
```

#### 1.3.3 — `get_spot_price`

```
test_get_spot_price_known
  GIVEN: ticker="NVDA"
  THEN:  price == 875.20, currency == "USD"

test_get_spot_price_unknown_returns_none
  GIVEN: ticker="ZZZZ"
  THEN:  result is None
```

#### 1.3.4 — `get_price_on_date`

```
test_get_price_on_date_returns_bar
  GIVEN: ticker="AAPL", date=<any date in OHLCV>
  THEN:  open, high, low, close, volume all present and numeric

test_get_price_on_date_unknown_date_returns_none
  GIVEN: ticker="AAPL", date="1990-01-01"
  THEN:  result is None
```

#### 1.3.5 — `list_instruments`

```
test_list_instruments_all
  GIVEN: no exchange filter
  THEN:  len(result) == 6

test_list_instruments_by_exchange
  GIVEN: exchange="XLON"
  THEN:  all results have exchange == "XLON", len == 2

test_list_instruments_empty_exchange_returns_all
  GIVEN: exchange=None
  THEN:  len == 6
```

#### 1.3.6 — `get_ohlcv_history`

```
test_get_ohlcv_history_returns_ordered_bars
  GIVEN: ticker="MSFT", from_date="2026-02-01", to_date="2026-02-28"
  THEN:  bars sorted by date ascending, each bar has date/open/high/low/close/volume

test_get_ohlcv_history_unknown_ticker_returns_empty
  GIVEN: ticker="ZZZZ", from_date="2026-01-01", to_date="2026-05-01"
  THEN:  result == []

test_get_ohlcv_history_out_of_range_returns_empty
  GIVEN: ticker="AAPL", from_date="2020-01-01", to_date="2020-12-31"
  THEN:  result == []
```

#### 1.3.7 — `get_volume_history`

```
test_get_volume_history_only_has_date_and_volume
  GIVEN: ticker="TSLA", from_date="2026-03-01", to_date="2026-03-31"
  THEN:  each item has only keys "ticker", "date", "volume"
  AND:   no "close" or "open" keys present
```

#### 1.3.8 — `get_latest_trading_day`

```
test_get_latest_trading_day
  GIVEN: ticker="AAPL"
  THEN:  date == "2026-05-13"
```

#### 1.3.9 — `get_market_codes`

```
test_get_market_codes_nasdaq
  GIVEN: ticker="AAPL"
  THEN:  primary_mic == "XNAS", bloomberg_code == "AAPL US Equity", reuters_ric == "AAPL.O"

test_get_market_codes_lse
  GIVEN: ticker="BARC"
  THEN:  primary_mic == "XLON"

test_get_market_codes_unknown_returns_none
  GIVEN: ticker="ZZZZ"
  THEN:  result is None
```

#### 1.3.10 — `validate_market_code`

```
test_validate_market_code_match
  GIVEN: ticker="AAPL", exchange="XNAS"
  THEN:  is_match == True

test_validate_market_code_no_match
  GIVEN: ticker="AAPL", exchange="XLON"
  THEN:  is_match == False, primary_exchange == "XNAS"
```

### Step 1.4 — Run instrument tests

```bash
uv run python -m pytest tests/integration/test_instruments_service.py -v
```

All tests must pass before proceeding to Phase 2.

---

## Phase 2 — Client Service

**Goal:** Implement `clients.py`, extend `conftest.py`, write and pass all client service tests.

### Step 2.1 — Implement `clients.py`

**Data loaded at import time:**

```python
_CLIENTS:   dict[str, dict] = csv_table("clients.csv", "client_id")
_MANDATES:  dict[str, dict] = csv_table("mandates.csv", "client_id")
_HOLDINGS_RAW = csv_rows("holdings.csv")
_WATCHLIST_RAW = csv_rows("watchlist.csv")

# Index by client_id
from collections import defaultdict
_HOLDINGS: dict[str, list[dict]] = defaultdict(list)
for row in _HOLDINGS_RAW:
    _HOLDINGS[row["client_id"]].append(row)

_WATCHLIST: dict[str, list[str]] = defaultdict(list)
for row in _WATCHLIST_RAW:
    _WATCHLIST[row["client_id"]].append(row["ticker"])

# Inverse indexes
_TICKER_TO_HOLDERS:  dict[str, list[str]] = defaultdict(list)
_TICKER_TO_WATCHERS: dict[str, list[str]] = defaultdict(list)
for row in _HOLDINGS_RAW:
    _TICKER_TO_HOLDERS[row["ticker"]].append(row["client_id"])
for row in _WATCHLIST_RAW:
    _TICKER_TO_WATCHERS[row["ticker"]].append(row["client_id"])
```

**Tools to implement:**

| Tool | Key logic |
|---|---|
| `client_lookup` | Exact `client_id` match or case-insensitive name substring |
| `list_clients` | Return all client records |
| `get_holdings` | Return `_HOLDINGS[client_id]` |
| `get_holding` | Find single entry by `client_id` + `ticker` |
| `list_portfolio_tickers` | Distinct tickers from `_HOLDINGS[client_id]` |
| `get_watchlist` | Return `_WATCHLIST[client_id]` |
| `is_on_watchlist` | `ticker in _WATCHLIST[client_id]` |
| `get_mandate_document` | Return full text from `_MANDATES[client_id]` |
| `search_mandate_text` | Lexical: return sentences containing any query term |
| `list_mandate_documents` | Return id, version, date (no text) |
| `get_clients_holding` | Return `_TICKER_TO_HOLDERS[ticker]` |
| `get_clients_watching` | Return `_TICKER_TO_WATCHERS[ticker]` |

**`search_mandate_text` implementation note:**

Split `mandate_text` on `". "` to get sentences. Return sentences where any `query_term.lower()` appears in the sentence (case-insensitive). Include `matched_terms` as the subset of query terms that triggered each excerpt.

### Step 2.2 — Add lifecycle to `tests/integration/conftest.py`

Add a requested `clients_url` fixture in the same style as `instruments_url`. It must not be `autouse=True`; tests that need the Client Service request `clients_url` explicitly.

### Step 2.3 — Write `tests/integration/test_clients_service.py`

#### 2.3.1 — Auth guard

```
test_client_lookup_no_token_raises
```

#### 2.3.2 — `client_lookup`

```
test_client_lookup_by_id
  GIVEN: query="C001"
  THEN:  name == "Meridian Capital"

test_client_lookup_by_name_substring
  GIVEN: query="apex"
  THEN:  client_id == "C002"

test_client_lookup_unknown_returns_none
  GIVEN: query="ZZZZ"
  THEN:  result is None
```

#### 2.3.3 — `list_clients`

```
test_list_clients_returns_three
  THEN:  len(result) == 3
  AND:   client_ids are {"C001", "C002", "C003"}
```

#### 2.3.4 — `get_holdings`

```
test_get_holdings_c001
  GIVEN: client_id="C001"
  THEN:  tickers include "AAPL", "BARC", "VOD"
  AND:   AAPL quantity == 5000

test_get_holdings_unknown_returns_empty
  GIVEN: client_id="ZZZZ"
  THEN:  result == []

test_get_holdings_short_position
  GIVEN: client_id="C002"
  THEN:  TSLA quantity == -1000
```

#### 2.3.5 — `get_holding`

```
test_get_holding_found
  GIVEN: client_id="C001", ticker="BARC"
  THEN:  quantity == 12000

test_get_holding_not_held
  GIVEN: client_id="C001", ticker="NVDA"
  THEN:  result is None (C001 does not hold NVDA in snapshot)
```

#### 2.3.6 — `list_portfolio_tickers`

```
test_list_portfolio_tickers_c001
  GIVEN: client_id="C001"
  THEN:  sorted result == ["AAPL", "BARC", "VOD"]
```

#### 2.3.7 — `get_watchlist`

```
test_get_watchlist_c001
  GIVEN: client_id="C001"
  THEN:  result contains "NVDA" and "TSLA"

test_get_watchlist_unknown_returns_empty
  GIVEN: client_id="ZZZZ"
  THEN:  result == []
```

#### 2.3.8 — `is_on_watchlist`

```
test_is_on_watchlist_true
  GIVEN: client_id="C003", ticker="TSLA"
  THEN:  is_watched == True

test_is_on_watchlist_false
  GIVEN: client_id="C001", ticker="BARC"   # C001 holds BARC but does not watch it
  THEN:  is_watched == False
```

#### 2.3.9 — `get_mandate_document`

```
test_get_mandate_document_returns_text
  GIVEN: client_id="C001"
  THEN:  mandate_text contains "long-only"
  AND:   mandate_version == "v1"

test_get_mandate_document_unknown_returns_none
  GIVEN: client_id="ZZZZ"
  THEN:  result is None
```

#### 2.3.10 — `search_mandate_text`

```
test_search_mandate_text_finds_short_term
  GIVEN: client_id="C002", query_terms=["short"]
  THEN:  at least one excerpt returned
  AND:   "short" in excerpt.lower()

test_search_mandate_text_esg
  GIVEN: client_id="C003", query_terms=["ESG", "exclusion"]
  THEN:  at least one excerpt with matched_terms containing "ESG" or "exclusion"

test_search_mandate_text_no_match_returns_empty
  GIVEN: client_id="C001", query_terms=["commodities"]
  THEN:  result == []
```

#### 2.3.11 — `list_mandate_documents`

```
test_list_mandate_documents_count
  THEN:  len == 3
  AND:   no "mandate_text" key in any row (text excluded for brevity)
```

#### 2.3.12 — Inverse lookups

```
test_get_clients_holding_aapl
  GIVEN: ticker="AAPL"
  THEN:  result contains "C001", "C002", "C003"

test_get_clients_watching_nvda
  GIVEN: ticker="NVDA"
  THEN:  result contains "C001" and "C003"

test_get_clients_holding_not_held
  GIVEN: ticker="ZZZZ"
  THEN:  result == []
```

### Step 2.4 — Run client tests

```bash
uv run python -m pytest tests/integration/test_clients_service.py -v
```

All must pass.

---

## Phase 3 — Trade Service

**Goal:** Implement `trades.py`, extend `conftest.py`, write and pass all trade service tests.

### Step 3.1 — Implement `trades.py`

**Data loaded at import time:**

```python
_ALL_TRADES: list[dict] = csv_rows("trades.csv")

# Indexes for fast filtering
from collections import defaultdict
_BY_CLIENT:     dict[str, list[dict]] = defaultdict(list)
_BY_TICKER:     dict[str, list[dict]] = defaultdict(list)
_BY_TRADE_ID:   dict[str, dict]       = {}
_BY_CLIENT_TICKER: dict[tuple, list[dict]] = defaultdict(list)

for row in _ALL_TRADES:
    _BY_CLIENT[row["client_id"]].append(row)
    _BY_TICKER[row["ticker"]].append(row)
    _BY_TRADE_ID[row["trade_id"]] = row
    _BY_CLIENT_TICKER[(row["client_id"], row["ticker"])].append(row)
```

**Tools to implement:**

| Tool | Key logic |
|---|---|
| `get_trades` | Filter by any combination of `client_id`, `ticker`, `from_date`, `to_date` |
| `get_trade` | Direct lookup in `_BY_TRADE_ID` |
| `get_last_trade` | Latest `trade_date` in `_BY_CLIENT_TICKER[(client_id, ticker)]` |
| `list_clients_traded_instrument` | Distinct `client_id` values in `_BY_TICKER[ticker]`, optional date filter |
| `get_trade_activity_window` | Per-ticker summary of count/qty for `client_id` within date range |
| `get_trade_summary` | Count buys/sells, net qty, avg prices from `_BY_CLIENT_TICKER` |
| `get_average_execution_price` | Weighted avg by side/date within `_BY_CLIENT_TICKER` |
| `get_realised_pnl` | FIFO matching on sorted buy/sell trades |
| `list_traded_instruments` | Distinct tickers in `_BY_CLIENT[client_id]` |

**`get_realised_pnl` FIFO algorithm:**

```
buys  = sorted buy trades by trade_date ascending
sells = sorted sell trades by trade_date ascending
buy_queue = [(qty, price), ...]
for each sell:
    remaining = sell.quantity
    while remaining > 0 and buy_queue:
        bq, bp = buy_queue.pop(0)
        matched = min(bq, remaining)
        pnl += matched * (sell.price - bp)
        if bq > matched: buy_queue.insert(0, (bq - matched, bp))
        remaining -= matched
```

### Step 3.2 — Add lifecycle to `tests/integration/conftest.py`

Add a requested `trades_url` fixture in the same style as `instruments_url`. It must not be `autouse=True`; tests that need the Trade Service request `trades_url` explicitly.

### Step 3.3 — Write `tests/integration/test_trades_service.py`

#### 3.3.1 — Auth guard

```
test_get_trades_no_token_raises
```

#### 3.3.2 — `get_trades` filtering

```
test_get_trades_by_client
  GIVEN: client_id="C001"
  THEN:  all rows have client_id == "C001"
  AND:   len >= 5  (T0001–T0004, T0015–T0016, T0019–T0020)

test_get_trades_by_ticker
  GIVEN: ticker="NVDA"
  THEN:  all rows have ticker == "NVDA"

test_get_trades_by_client_and_ticker
  GIVEN: client_id="C002", ticker="AAPL"
  THEN:  trade_ids contain "T0005" and "T0006"

test_get_trades_date_filter
  GIVEN: from_date="2026-03-01", to_date="2026-03-31"
  THEN:  all trade_dates within March 2026

test_get_trades_no_filter_returns_all
  THEN:  len == 20
```

#### 3.3.3 — `get_trade`

```
test_get_trade_known
  GIVEN: trade_id="T0007"
  THEN:  client_id == "C002", ticker == "NVDA", side == "buy", price == 820.00

test_get_trade_unknown_returns_none
  GIVEN: trade_id="T9999"
  THEN:  result is None
```

#### 3.3.4 — `get_last_trade`

```
test_get_last_trade_c002_nvda
  GIVEN: client_id="C002", ticker="NVDA"
  THEN:  trade_date == "2026-04-10"  (T0008 is later than T0007)

test_get_last_trade_no_trades_returns_none
  GIVEN: client_id="C001", ticker="MSFT"  # C001 never traded MSFT
  THEN:  result is None
```

#### 3.3.5 — `list_clients_traded_instrument`

```
test_list_clients_traded_aapl
  GIVEN: ticker="AAPL"
  THEN:  result contains "C001", "C002", "C003"

test_list_clients_traded_aapl_date_filter
  GIVEN: ticker="AAPL", from_date="2026-04-01", to_date="2026-05-01"
  THEN:  result contains "C002" and "C003" (T0006, T0014 both in range)
  AND:   result does not contain "C001" (C001's AAPL activity is before the range)

test_list_clients_traded_unknown_ticker
  GIVEN: ticker="ZZZZ"
  THEN:  result == []
```

#### 3.3.6 — `get_trade_activity_window`

```
test_get_trade_activity_window_c001
  GIVEN: client_id="C001", from_date="2026-02-01", to_date="2026-05-13"
  THEN:  at least three entries (AAPL, BARC, VOD, NVDA, TSLA)
  AND:   each entry has trade_count >= 1
```

#### 3.3.7 — `get_trade_summary`

```
test_get_trade_summary_c002_aapl
  GIVEN: client_id="C002", ticker="AAPL"
  THEN:  total_buys == 1, total_sells == 1
  AND:   net_quantity == 0  (bought 2000, sold 2000)
  AND:   avg_buy_price == 178.50
  AND:   avg_sell_price == 194.20

test_get_trade_summary_no_trades
  GIVEN: client_id="C001", ticker="MSFT"
  THEN:  total_buys == 0, total_sells == 0, net_quantity == 0
```

#### 3.3.8 — `get_average_execution_price`

```
test_get_average_execution_price_buy_side
  GIVEN: client_id="C002", ticker="AAPL", side="buy"
  THEN:  avg_price == 178.50, total_quantity == 2000

test_get_average_execution_price_both_sides
  GIVEN: client_id="C002", ticker="AAPL", side=None
  THEN:  trade_count == 2
```

#### 3.3.9 — `get_realised_pnl`

```
test_get_realised_pnl_c002_aapl
  GIVEN: client_id="C002", ticker="AAPL"
  # T0005 buy 2000 @ 178.50; T0006 sell 2000 @ 194.20
  THEN:  realised_pnl == (194.20 - 178.50) * 2000 == 31400.00
  AND:   matched_trades == 1

test_get_realised_pnl_partial_round_trip
  GIVEN: client_id="C001", ticker="AAPL"
  # T0001 buy 1000 @ 182.10; T0002 sell 500 @ 191.30
  THEN:  realised_pnl == (191.30 - 182.10) * 500 == 4600.00
  AND:   matched_trades == 1

test_get_realised_pnl_no_sells_returns_zero
  GIVEN: client_id="C001", ticker="VOD"
  # T0004 buy only
  THEN:  realised_pnl == 0.0, matched_trades == 0
```

#### 3.3.10 — `list_traded_instruments`

```
test_list_traded_instruments_c001
  GIVEN: client_id="C001"
  THEN:  sorted result contains "AAPL", "BARC", "NVDA", "TSLA", "VOD"

test_list_traded_instruments_unknown_client
  GIVEN: client_id="ZZZZ"
  THEN:  result == []
```

### Step 3.4 — Run trade tests

```bash
uv run python -m pytest tests/integration/test_trades_service.py -v
```

---

## Phase 4 — Analytics Service

**Goal:** Implement `analytics.py`, extend `conftest.py`, write and pass all analytics tests. The service is stateless — it takes data in, returns a result.

### Step 4.1 — Implement `analytics.py`

No CSV loading. Every tool accepts `bars: list[dict]` (same schema as `OHLCVBar`).

**Tools to implement:**

| Tool | Formula |
|---|---|
| `historical_volatility` | `std(log(close[i]/close[i-1])) * sqrt(252)`, rolling `window` |
| `vwap` | `sum((o+h+l+c)/4 * vol) / sum(vol)` |
| `simple_return` | `(last_close / first_close - 1) * 100` |
| `max_drawdown` | Running peak, record max trough from peak |
| `price_momentum` | Last close vs N-day SMA of close |
| `position_market_value` | `quantity * spot_price` |
| `compare_execution_to_vwap` | `(exec - vwap) / vwap * 10000` basis points; `favourable` is True when: buy exec < vwap or sell exec > vwap |

**`historical_volatility` implementation note:**

```python
import math

closes = [float(b["close"]) for b in bars]
if len(closes) < window + 1:
    return {"annualised_vol": None, "observations": 0, ...}
log_rets = [math.log(closes[i] / closes[i-1]) for i in range(1, len(closes))]
used = log_rets[-window:]
mean = sum(used) / len(used)
variance = sum((r - mean)**2 for r in used) / (len(used) - 1)
annualised_vol = math.sqrt(variance) * math.sqrt(252)
```

### Step 4.2 — Add lifecycle to `tests/integration/conftest.py`

Add a requested `analytics_url` fixture in the same style as `instruments_url`. It must not be `autouse=True`; tests that need the Analytics Service request `analytics_url` explicitly.

### Step 4.3 — Write `tests/integration/test_analytics_service.py`

To call analytics tools in tests, the test must first build a `bars` list. These are constructed inline from known values (not from the OHLCV CSVs directly) so the expected results can be computed by hand. This keeps analytics tests self-contained.

#### 4.3.1 — Auth guard

```
test_historical_volatility_no_token_raises
```

#### 4.3.2 — `historical_volatility`

```
test_historical_volatility_sufficient_data
  GIVEN: 25 synthetic bars with deterministic prices
  THEN:  annualised_vol is a float > 0
  AND:   observations == 20  (window bars used)

test_historical_volatility_insufficient_data
  GIVEN: 5 bars, window=20
  THEN:  annualised_vol is None, observations == 0
```

#### 4.3.3 — `vwap`

```
test_vwap_simple
  GIVEN: 3 bars with known o/h/l/c/volume
  THEN:  vwap == expected weighted value (computed by hand)
  AND:   total_volume == sum of volumes

test_vwap_from_to_dates
  GIVEN: bars spanning two dates
  THEN:  from_date and to_date reflect first and last bar
```

#### 4.3.4 — `simple_return`

```
test_simple_return_positive
  GIVEN: bars with first close=100.0, last close=110.0
  THEN:  return_pct == 10.0

test_simple_return_negative
  GIVEN: bars with first close=200.0, last close=190.0
  THEN:  return_pct == -5.0
```

#### 4.3.5 — `max_drawdown`

```
test_max_drawdown_falling_sequence
  GIVEN: closes = [100, 120, 80, 90, 70, 110]
  # peak=120 at idx1, trough=70 at idx4: drawdown = (70-120)/120 = -41.67%
  THEN:  max_drawdown_pct ≈ -41.67
  AND:   peak_close == 120.0, trough_close == 70.0

test_max_drawdown_monotone_rising
  GIVEN: closes strictly increasing
  THEN:  max_drawdown_pct == 0.0
```

#### 4.3.6 — `price_momentum`

```
test_price_momentum_above_ma
  GIVEN: 25 bars where last close is above the 20-day SMA
  THEN:  signal == "above_ma"

test_price_momentum_insufficient_data
  GIVEN: 5 bars, window=20
  THEN:  signal == "insufficient_data"
```

#### 4.3.7 — `position_market_value`

```
test_position_market_value_long
  GIVEN: quantity=5000, spot_price=189.45, currency="USD"
  THEN:  market_value == 947250.0

test_position_market_value_short
  GIVEN: quantity=-1000, spot_price=172.60
  THEN:  market_value == -172600.0
```

#### 4.3.8 — `compare_execution_to_vwap`

```
test_compare_execution_to_vwap_buy_favourable
  GIVEN: side="buy", execution_price=178.50, vwap=180.00
  THEN:  favourable == True  (bought below VWAP)
  AND:   basis_points ≈ -83.3

test_compare_execution_to_vwap_sell_favourable
  GIVEN: side="sell", execution_price=194.20, vwap=190.00
  THEN:  favourable == True  (sold above VWAP)

test_compare_execution_to_vwap_buy_unfavourable
  GIVEN: side="buy", execution_price=195.00, vwap=190.00
  THEN:  favourable == False
```

### Step 4.4 — Run analytics tests

```bash
uv run python -m pytest tests/integration/test_analytics_service.py -v
```

---

## Phase 5 — Full Suite Regression

After all four phases pass in isolation, run the complete test suite to confirm nothing regressed in the pre-existing tests.

```bash
uv run python -m pytest tests/ -v
```

Fix any failures before considering the implementation done.

---

## Implementation Order Checklist

```
[ ] Phase 0.1  Directory skeleton
[ ] Phase 0.2  _server.py
[ ] Phase 0.3  _data_loader.py
[ ] Phase 0.4  CSV files (instruments, spot, clients, mandates, holdings, watchlist, trades)
[ ] Phase 0.5  Run generate_ohlcv.py, commit six OHLCV CSVs
[ ] Phase 0.6  conftest.py skeleton
[ ] Phase 0.7  Verify shared infrastructure imports
[ ] Phase 0.8  Green: uv run python -m pytest tests/integration/test_fixture_data_integrity.py -v

[ ] Phase 1.1  instruments.py (all 9 tools)
[ ] Phase 1.2  instruments_url fixture in tests/integration/conftest.py
[ ] Phase 1.3  test_instruments_service.py (all 16 test cases)
[ ] Phase 1.4  Green: uv run python -m pytest tests/integration/test_instruments_service.py -v

[ ] Phase 2.1  clients.py (all 12 tools)
[ ] Phase 2.2  clients_url fixture in tests/integration/conftest.py
[ ] Phase 2.3  test_clients_service.py (all 18 test cases)
[ ] Phase 2.4  Green: uv run python -m pytest tests/integration/test_clients_service.py -v

[ ] Phase 3.1  trades.py (all 9 tools)
[ ] Phase 3.2  trades_url fixture in tests/integration/conftest.py
[ ] Phase 3.3  test_trades_service.py (all 18 test cases)
[ ] Phase 3.4  Green: uv run python -m pytest tests/integration/test_trades_service.py -v

[ ] Phase 4.1  analytics.py (all 7 tools)
[ ] Phase 4.2  analytics_url fixture in tests/integration/conftest.py
[ ] Phase 4.3  test_analytics_service.py (all 12 test cases)
[ ] Phase 4.4  Green: uv run python -m pytest tests/integration/test_analytics_service.py -v

[ ] Phase 5    Green: uv run python -m pytest tests/ -v
```

---

## Notes

- Service URL fixtures live in `tests/integration/conftest.py`, because pytest discovers conftest files only in the test file's directory and its parents. A sibling `tests/fixtures/mcp_services/conftest.py` would not be visible to `tests/integration/*.py`.
- Service fixtures are requested explicitly, not `autouse=True`. This keeps service implementation incremental: adding the Client Service fixture does not force every unrelated integration test to import or start it.
- Do not use `pytest-asyncio` inside the fixture server files. The server threads use their own event loops. Only the test functions themselves use `async def` with `asyncio_mode = "auto"`.
- `tests/integration/conftest.py` already imports the existing `mock_mcp_server` fixtures. Extend that file carefully without changing existing fixtures.
