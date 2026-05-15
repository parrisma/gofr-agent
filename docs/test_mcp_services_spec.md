# Test MCP Services Spec

> **Status:** Draft v0.4  
> **Date:** 2026-05-13  
> **Scope:** Four in-process test MCP services used to validate multi-service reasoning by `gofr-agent`. These services contain synthetic but internally consistent data so that cross-service questions have deterministic, verifiable answers.

---

## Purpose

The goal of these services is to prove that `gofr-agent` can receive a single natural-language question, discover and call tools across multiple independent MCP servers, and synthesise a coherent answer that could not have been produced by any single service alone.

Example cross-service questions that the test suite should be able to assert on:

- *"What is the current volatility of instruments held by client Meridian Capital?"*
- *"Which clients have a mandate to trade AAPL and what positions do they currently hold?"*
- *"Show me the trade history for TSLA for any client that has it on their watchlist."*
- *"What was the realised P&L for client Apex Fund on their NVDA trades last quarter?"*

All four services are implemented as FastMCP instances running in-process (same pattern as `tests/integration/mock_mcp_server.py`) and are wired together via a shared conftest fixture.

---

## Authorization

All four services participate in the same JWT bearer token contract described in `auth_mini_spec.md`.

### Contract

Every MCP request must carry an `Authorization: Bearer <token>` header. Each service extracts the token from the header and verifies that it is present and non-empty. **No cryptographic validation is performed at this stage** — the check is structural only (token exists and is a non-empty string). If the header is absent or the token is empty the service returns an MCP error with code `401`. Any non-empty token is accepted.

This keeps the full auth propagation code path exercised — `gofr-agent` must forward the caller's JWT to every downstream service it calls — without requiring a real identity provider in tests.

### Test Token

The conftest fixture mints a single static test JWT and stores it in the session fixture:

```python
TEST_JWT = "test-token-gofr-fixtures"
```

All test calls to `gofr-agent`, and all direct tool calls in unit-style fixture tests, must supply `Authorization: Bearer test-token-gofr-fixtures`.

---

## Service Overview

| Service | Short name | Topic |
|---|---|---|
| Instrument Service | `instruments` | Cash equity reference data, spot prices, OHLCV history |
| Client Service | `clients` | Institutional client profiles, holdings, watchlists, mandates |
| Trade Service | `trades` | Trade blotter — executions per client per instrument |
| Analytics Service | `analytics` | Derived metrics: historical vol, VWAP, simple return, momentum |

---

## Peer Review of Tool Binding Design

The proposal should optimise for MCP interfaces that are small, composable, and domain-bounded. A demo question should require the agent to discover facts in one service, normalise identifiers in another, and only then call a downstream calculation or retrieval tool. Tools should not return fully joined answers that hide this reasoning path.

### Review Findings

- The original bindings had the right service boundaries, but some services needed more granular point lookups so the agent can reason step-by-step instead of pulling broad result sets.
- Instrument tools should separate identity resolution, point-in-time price lookup, date-range history, and volume retrieval. This lets the agent answer both "current exposure" and "historical behaviour" prompts using different chains.
- Client tools should expose both portfolio-level and single-position queries, plus written mandate primitives. The Client Service should return mandate text and relevant text excerpts, while the agent extracts semantic meaning by comparing the written policy with already-resolved instrument facts from the Instrument Service.
- Trade tools should include narrow activity and aggregation queries in addition to raw blotter retrieval. This supports questions like "who traded this watched name recently?" without requiring the agent to fetch the whole blotter.
- Analytics tools should remain stateless and accept market data supplied by the agent. This intentionally forces the Instrument Service -> Analytics Service hop for volatility, returns, drawdown, VWAP, and momentum.

### Binding Principles

- **Resolve before acting:** natural-language names should first be normalised to stable `client_id` and `ticker` values.
- **One domain per service:** no service owns another service's data. The Client Service owns written mandate documents, but it does not convert them into fully structured compliance decisions. The agent performs that semantic interpretation.
- **Prefer narrow calls:** point lookup tools exist for single client, single instrument, single date, and single trade questions.
- **Support fan-out:** tools expose list and inverse lookup bindings, such as "clients holding ticker" and "clients that traded ticker," so the agent can branch from one discovered entity to many related entities.
- **Keep calculations explicit:** analytics receives bars, quantities, or prices supplied by the agent, making the reasoning chain observable in tests.

---

## Synthetic Data

All services share a fixed universe so cross-service queries produce consistent results. Data is stored as editable CSV files under `tests/fixtures/mcp_services/data/` and loaded at service startup. Edit the CSVs to adjust the universe without touching Python code.

### CSV File Layout

```
tests/fixtures/mcp_services/data/
  instruments.csv       # ticker, isin, exchange, name, currency, bloomberg_code, reuters_ric, sedol
  spot_prices.csv       # ticker, price, currency, as_of
  ohlcv/
    AAPL.csv            # date, open, high, low, close, volume  (90 rows)
    MSFT.csv
    NVDA.csv
    TSLA.csv
    BARC.csv
    VOD.csv
  clients.csv           # client_id, name
  mandates.csv          # client_id, mandate_version, effective_date, mandate_text
  holdings.csv          # client_id, ticker, quantity
  watchlist.csv         # client_id, ticker
  trades.csv            # trade_id, client_id, ticker, side, quantity, price, currency, trade_date
```

### Instruments (`instruments.csv`)

```
ticker,isin,exchange,name,currency,bloomberg_code,reuters_ric,sedol
AAPL,US0378331005,XNAS,Apple Inc,USD,AAPL US Equity,AAPL.O,2046251
MSFT,US5949181045,XNAS,Microsoft Corp,USD,MSFT US Equity,MSFT.O,2588173
NVDA,US67066G1040,XNAS,NVIDIA Corp,USD,NVDA US Equity,NVDA.O,2379504
TSLA,US88160R1014,XNAS,Tesla Inc,USD,TSLA US Equity,TSLA.O,B616C79
BARC,GB0031348658,XLON,Barclays PLC,GBP,BARC LN Equity,BARC.L,0798059
VOD,GB00BH4HKS39,XLON,Vodafone Group PLC,GBP,VOD LN Equity,VOD.L,BH4HKS3
```

### Clients (`clients.csv`)

```
client_id,name
C001,Meridian Capital
C002,Apex Fund
C003,Blue Ridge Partners
```

### Mandates (`mandates.csv`)

```
client_id,mandate_version,effective_date,mandate_text
C001,v1,2026-01-01,"Meridian Capital is authorised for long-only trading in listed cash equities on US and UK primary exchanges. The portfolio must not initiate or maintain single-name short positions. Purchases of listed ordinary shares and sales that reduce or close existing long positions are permitted. Trading in derivatives, private securities, crypto assets, or non-US/non-UK venues is outside mandate."
C002,v1,2026-01-01,"Apex Fund may trade long and short positions in listed US cash equities. Short sales are permitted where the issuer's primary listing is a US exchange. The mandate does not permit UK or European listed equities, depositary receipts used as substitutes for restricted venues, derivatives, or unlisted securities."
C003,v1,2026-01-01,"Blue Ridge Partners operates a long-only ESG screened mandate for US listed cash equities. The client may buy or sell listed US ordinary shares to build, reduce, or exit long positions. The client must not establish short exposure. Securities with an internal ESG exclusion flag, non-US primary listings, derivatives, and highly leveraged products are outside mandate."
```

*Mandates are deliberately written as natural-language policy text. They are not pre-parsed into `direction`, `allowed_exchanges`, or `esg_screen` fields. The test is whether the agent can read the text, extract semantic constraints, and apply them to instrument facts from other MCP services.*

### Holdings (`holdings.csv`)

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

### Watchlist (`watchlist.csv`)

```
client_id,ticker
C001,NVDA
C001,TSLA
C002,BARC
C003,NVDA
C003,TSLA
C003,VOD
```

### Spot Prices (`spot_prices.csv`)

```
ticker,price,currency,as_of
AAPL,189.45,USD,2026-05-13
MSFT,415.30,USD,2026-05-13
NVDA,875.20,USD,2026-05-13
TSLA,172.60,USD,2026-05-13
BARC,2.14,GBP,2026-05-13
VOD,0.71,GBP,2026-05-13
```

### OHLCV History (`ohlcv/<TICKER>.csv`)

Each file contains 90 trading-day rows ending on 2026-05-13. Column order: `date,open,high,low,close,volume`. Prices are synthetic but internally monotone-random-walk consistent; trade prices in `trades.csv` fall within the day's `[low, high]` band.

### Trades (`trades.csv`)

~30 rows covering all three clients across multiple instruments and dates.

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
... (rows continue to ~30 total)
```

*The full `trades.csv` is the authoritative record. The excerpt above is for illustration; the actual file in the repo has all rows.*

---

## 1. Instrument Service (`instruments`)

### 1.1 Responsibility

Canonical reference data for cash equity instruments. Provides lookup by ticker or ISIN, spot prices, and daily OHLCV history. Knows nothing about who holds or trades an instrument.

### 1.2 Tool Bindings

#### `instrument_lookup`

Resolve a human-readable name, ticker, or ISIN to the canonical instrument record.

```
instrument_lookup(query: str) -> InstrumentRecord | None

InstrumentRecord:
  ticker:    str          # e.g. "AAPL"
  isin:      str          # e.g. "US0378331005"
  name:      str          # e.g. "Apple Inc"
  exchange:  str          # MIC code, e.g. "XNAS"
  currency:  str          # ISO 4217, e.g. "USD"
```

*`query` is matched case-insensitively against ticker, ISIN, and name substring. Returns `None` when no match is found.*

---

#### `get_spot_price`

Return the current (synthetic) mid price for an instrument.

```
get_spot_price(ticker: str) -> SpotPrice | None

SpotPrice:
  ticker:     str
  price:      float
  currency:   str
  as_of:      str   # ISO 8601 date, e.g. "2026-05-13"
```

---

#### `get_price_on_date`

Return the close price and daily volume for one instrument on one trading date.

```
get_price_on_date(ticker: str, date: str) -> DailyPrice | None

DailyPrice:
  ticker:   str
  date:     str
  open:     float
  high:     float
  low:      float
  close:    float
  volume:   int
```

*This is the narrow point lookup used when a question mentions a specific trade date, valuation date, or "price on the day of the trade." Returns `None` when there is no bar for the requested date.*

---

#### `list_instruments`

Return all instruments in the service universe, optionally filtered by exchange.

```
list_instruments(exchange: str | None = None) -> list[InstrumentRecord]
```

*When `exchange` is provided it is matched as a MIC code (e.g. `"XNAS"`, `"XLON"`). Returns all instruments when `exchange` is `None`.*

---

#### `get_ohlcv_history`

Return daily OHLCV bars for an instrument over a date range.

```
get_ohlcv_history(
    ticker: str,
    from_date: str,   # ISO 8601, inclusive
    to_date:   str,   # ISO 8601, inclusive
) -> list[OHLCVBar]

OHLCVBar:
  date:   str
  open:   float
  high:   float
  low:    float
  close:  float
  volume: int
```

*Returns bars in ascending date order. Returns an empty list if the ticker is unknown or the date range contains no data. Synthetic data covers the 90 days prior to the spec date.*

---

#### `get_volume_history`

Return daily traded volume only for an instrument over a date range.

```
get_volume_history(
    ticker: str,
    from_date: str,
    to_date: str,
) -> list[VolumePoint]

VolumePoint:
  ticker: str
  date:   str
  volume: int
```

*This binding is intentionally narrower than `get_ohlcv_history` so volume-only questions do not require moving unnecessary price data through the agent loop.*

---

#### `get_latest_trading_day`

Return the latest available trading day for one instrument.

```
get_latest_trading_day(ticker: str) -> TradingDay | None

TradingDay:
  ticker: str
  date:   str
```

*Useful when the user asks for "latest", "current", or "as of now" and the agent needs a concrete date before fetching history or calculating analytics.*

---

#### `get_market_codes`

Return all exchange and market-segment codes relevant to an instrument.

```
get_market_codes(ticker: str) -> MarketCodes | None

MarketCodes:
  ticker:          str
  primary_mic:     str   # e.g. "XNAS"
  bloomberg_code:  str   # e.g. "AAPL US Equity"
  reuters_ric:     str   # e.g. "AAPL.O"
  sedol:           str   # 7-character SEDOL
```

---

#### `validate_market_code`

Check whether an instrument trades on a supplied exchange MIC.

```
validate_market_code(ticker: str, exchange: str) -> MarketCodeValidation

MarketCodeValidation:
  ticker:           str
  exchange:         str
  primary_exchange: str
  is_match:         bool
```

*Used with Client Service mandate text: the agent first resolves the instrument exchange here, then compares it with constraints it extracts from the written client mandate.*

---

### 1.3 Reasoning Notes

The agent must call `instrument_lookup` to normalise free-text mentions of an instrument before passing tickers to other services. `get_ohlcv_history` is the primary input for analytics tools.

---

## 2. Client Service (`clients`)

### 2.1 Responsibility

Institutional client master. Owns client identity, current holdings snapshot, watchlists, and trading mandates. Has no knowledge of trade execution details or price data.

### 2.2 Tool Bindings

#### `client_lookup`

Resolve a name or client ID to the canonical client record.

```
client_lookup(query: str) -> ClientRecord | None

ClientRecord:
  client_id:  str   # e.g. "C001"
  name:       str   # e.g. "Meridian Capital"
```

*`query` is matched against client ID (exact) and name (case-insensitive substring).*

---

#### `list_clients`

Return all client records.

```
list_clients() -> list[ClientRecord]
```

---

#### `get_holdings`

Return the current holdings snapshot for a client.

```
get_holdings(client_id: str) -> list[Holding]

Holding:
  client_id:  str
  ticker:     str
  quantity:   int   # negative = short position
```

*Returns an empty list for unknown client IDs.*

---

#### `get_holding`

Return one client's holding in one instrument.

```
get_holding(client_id: str, ticker: str) -> Holding | None
```

*Returns `None` if the client has no current position in the ticker. This avoids requiring the agent to fetch and scan an entire holdings list for single-instrument questions.*

---

#### `list_portfolio_tickers`

Return distinct tickers currently held by a client.

```
list_portfolio_tickers(client_id: str) -> list[str]
```

*Useful when the next step is to call Instrument or Analytics tools for every position without needing quantities yet.*

---

#### `get_watchlist`

Return the tickers on a client's care (watch) list.

```
get_watchlist(client_id: str) -> list[str]
```

*Returns an empty list for unknown client IDs.*

---

#### `is_on_watchlist`

Return whether one instrument is on a client's care list.

```
is_on_watchlist(client_id: str, ticker: str) -> WatchlistCheck

WatchlistCheck:
  client_id: str
  ticker:    str
  is_watched: bool
```

---

#### `get_mandate_document`

Return the written trading mandate for a client.

```
get_mandate_document(client_id: str) -> MandateDocument | None

MandateDocument:
  client_id:        str
  mandate_version: str
  effective_date:  str
  mandate_text:    str
```

*The returned text is the authoritative mandate. It is intentionally not normalised into fields such as `direction` or `allowed_exchanges`; the agent must infer those constraints from the prose.*

---

#### `search_mandate_text`

Return written mandate excerpts containing one or more query terms.

```
search_mandate_text(
    client_id: str,
    query_terms: list[str],
) -> list[MandateExcerpt]

MandateExcerpt:
  client_id:        str
  mandate_version: str
  excerpt:          str
  matched_terms:    list[str]
```

*This is a lexical excerpt helper, not a semantic classifier. For example, querying `['short', 'US', 'UK']` may return the relevant mandate sentences, but the agent still has to decide whether a proposed trade is permitted.*

---

#### `list_mandate_documents`

Return metadata for all available mandate documents.

```
list_mandate_documents() -> list[MandateDocumentSummary]

MandateDocumentSummary:
  client_id:        str
  mandate_version: str
  effective_date:  str
```

*Supports discovery workflows where the agent needs to inspect mandate text across several clients before filtering them semantically.*

---

#### `get_clients_holding`

Return all client IDs that hold a given ticker (long or short).

```
get_clients_holding(ticker: str) -> list[str]
```

*Supports cross-service queries of the form "which clients hold AAPL?".*

---

#### `get_clients_watching`

Return all client IDs that have a given ticker on their watchlist.

```
get_clients_watching(ticker: str) -> list[str]
```

---

### 2.3 Reasoning Notes

`get_mandate_document` and `search_mandate_text` are essential for compliance-style questions ("is this client allowed to trade this?"). The Client Service supplies written policy text only; the agent must extract semantic constraints such as allowed venues, long-only restrictions, short-sale permissions, and ESG language. `get_clients_holding` and `get_clients_watching` enable fan-out queries where the agent needs to iterate over clients to gather trade or analytics data per instrument.

---

## 3. Trade Service (`trades`)

### 3.1 Responsibility

Execution blotter. Records every synthetic trade done by a client in an instrument. Knows nothing about current reference prices or client profiles.

### 3.2 Synthetic Trade Data

Loaded from `tests/fixtures/mcp_services/data/trades.csv`. A fixed set of ~30 trade records spread across clients and instruments, covering the same 90-day window as the OHLCV history. Trades include buys and sells; quantities and prices are consistent with the OHLCV data (prices lie within the day's high/low band). Edit the CSV to add or adjust trades without modifying any Python code.

### 3.3 Tool Bindings

#### `get_trades`

Return trades filtered by client, instrument, and/or date range.

```
get_trades(
    client_id:  str | None = None,
    ticker:     str | None = None,
    from_date:  str | None = None,   # ISO 8601, inclusive
    to_date:    str | None = None,   # ISO 8601, inclusive
) -> list[Trade]

Trade:
  trade_id:   str     # e.g. "T0042"
  client_id:  str
  ticker:     str
  side:       str     # "buy" | "sell"
  quantity:   int     # always positive
  price:      float
  currency:   str
  trade_date: str     # ISO 8601
```

*All parameters are optional; omitting all returns the full blotter. At least one filter should be supplied for sensible results — the agent is expected to learn this from the tool description.*

---

#### `get_trade`

Return a single trade record by trade ID.

```
get_trade(trade_id: str) -> Trade | None
```

---

#### `get_last_trade`

Return the most recent trade for a client/instrument pair.

```
get_last_trade(client_id: str, ticker: str) -> Trade | None
```

*Used for questions that compare the last execution price with current spot or recent VWAP. The spot or VWAP still comes from other services.*

---

#### `list_clients_traded_instrument`

Return distinct client IDs that traded a ticker in an optional date range.

```
list_clients_traded_instrument(
    ticker: str,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[str]
```

*This is the inverse of `list_traded_instruments` and enables fan-out from an instrument to the clients with activity in that name.*

---

#### `get_trade_activity_window`

Return a compact activity summary for one client over a date range.

```
get_trade_activity_window(
    client_id: str,
    from_date: str,
    to_date: str,
) -> list[TradeActivity]

TradeActivity:
  client_id:     str
  ticker:        str
  trade_count:   int
  gross_quantity: int
  net_quantity:  int
```

*Useful when the agent needs to identify which instruments were active before deciding which narrower trade or analytics calls to make.*

---

#### `get_trade_summary`

Return aggregated buy/sell counts and net quantity for a client/instrument pair.

```
get_trade_summary(
    client_id: str,
    ticker:    str,
) -> TradeSummary

TradeSummary:
  client_id:    str
  ticker:       str
  total_buys:   int   # number of buy trades
  total_sells:  int   # number of sell trades
  net_quantity: int   # total bought minus total sold (may be negative)
  avg_buy_price:  float | None
  avg_sell_price: float | None
```

---

#### `get_average_execution_price`

Return side-specific average execution price for a client/instrument pair.

```
get_average_execution_price(
    client_id: str,
    ticker: str,
    side: str | None = None,      # "buy" | "sell" | None for both
    from_date: str | None = None,
    to_date: str | None = None,
) -> AverageExecutionPrice

AverageExecutionPrice:
  client_id:      str
  ticker:         str
  side:           str | None
  avg_price:      float | None
  total_quantity: int
  trade_count:    int
  currency:       str | None
```

*Designed for comparisons such as "did the client buy better than the period VWAP?" The agent must call Instrument Service for bars, Analytics Service for VWAP, and Trade Service for average execution.*

---

#### `get_realised_pnl`

Compute a simple FIFO realised P&L for a client's completed round-trip trades in an instrument.

```
get_realised_pnl(
    client_id: str,
    ticker:    str,
) -> RealisedPnL

RealisedPnL:
  client_id:      str
  ticker:         str
  currency:       str
  realised_pnl:   float   # positive = profit
  matched_trades: int     # number of matched buy/sell pairs
```

*Uses FIFO matching. Returns `realised_pnl = 0.0` and `matched_trades = 0` if no round trips exist.*

---

#### `list_traded_instruments`

Return the distinct tickers that a client has traded.

```
list_traded_instruments(client_id: str) -> list[str]
```

---

### 3.4 Reasoning Notes

`get_realised_pnl` requires the agent to know both `client_id` and `ticker`, which it must first obtain from the Client or Instrument service. `get_trades` with no filters is intentionally broad — the agent should prefer narrower calls; this mirrors real-world tool-use discipline.

---

## 4. Analytics Service (`analytics`)

### 4.1 Responsibility

Derived market metrics computed over OHLCV data supplied directly in the call. The Analytics Service is **stateless** — it holds no price data of its own. The agent must first fetch OHLCV history from the Instrument Service and then pass that data to Analytics tools.

This design forces multi-step reasoning: the agent cannot shortcut directly to a volatility answer without first fetching the raw price series.

### 4.2 Tool Bindings

#### `historical_volatility`

Compute annualised close-to-close historical volatility (standard deviation of log returns, scaled by √252).

```
historical_volatility(
    ticker:  str,
    bars:    list[OHLCVBar],   # same schema as instrument service
    window:  int = 20,         # rolling window in trading days
) -> VolatilityResult

VolatilityResult:
  ticker:          str
  window:          int
  annualised_vol:  float          # e.g. 0.32 = 32%
  as_of:           str            # date of the last bar used
  observations:    int            # number of bars consumed
```

*Returns `annualised_vol = None` and `observations = 0` when fewer than `window + 1` bars are supplied.*

---

#### `vwap`

Compute the volume-weighted average price over the supplied bars.

```
vwap(
    ticker: str,
    bars:   list[OHLCVBar],
) -> VWAPResult

VWAPResult:
  ticker:      str
  vwap:        float
  from_date:   str
  to_date:     str
  total_volume: int
```

*Uses `(open + high + low + close) / 4` as the typical price per bar.*

---

#### `simple_return`

Compute the total simple price return between the first and last bar.

```
simple_return(
    ticker: str,
    bars:   list[OHLCVBar],
) -> ReturnResult

ReturnResult:
  ticker:      str
  from_date:   str
  to_date:     str
  from_price:  float   # close of first bar
  to_price:    float   # close of last bar
  return_pct:  float   # (to_price / from_price - 1) * 100
```

---

#### `max_drawdown`

Compute maximum peak-to-trough drawdown over the supplied bars.

```
max_drawdown(
    ticker: str,
    bars:   list[OHLCVBar],
) -> DrawdownResult

DrawdownResult:
  ticker:          str
  max_drawdown_pct: float
  peak_date:       str
  trough_date:     str
  peak_close:      float
  trough_close:    float
```

*This gives the agent a risk-oriented metric that requires historical prices but no client data. Client-specific drawdown questions require a prior holdings or watchlist lookup.*

---

#### `price_momentum`

Return a simple momentum signal: whether the instrument's close is above or below its N-day moving average.

```
price_momentum(
    ticker: str,
    bars:   list[OHLCVBar],
    window: int = 20,
) -> MomentumResult

MomentumResult:
  ticker:       str
  window:       int
  last_close:   float
  moving_avg:   float
  signal:       str    # "above_ma" | "below_ma" | "insufficient_data"
  as_of:        str
```

---

#### `position_market_value`

Compute market value for one holding using a quantity and spot price supplied by the agent.

```
position_market_value(
    client_id: str,
    ticker: str,
    quantity: int,
    spot_price: float,
    currency: str,
) -> PositionMarketValue

PositionMarketValue:
  client_id:    str
  ticker:       str
  quantity:     int
  spot_price:   float
  currency:     str
  market_value: float
```

*The agent must fetch the holding from Client Service and spot price from Instrument Service before calling this tool.*

---

#### `compare_execution_to_vwap`

Compare a trade or average execution price to a VWAP supplied by the agent.

```
compare_execution_to_vwap(
    ticker: str,
    side: str,              # "buy" | "sell"
    execution_price: float,
    vwap: float,
) -> ExecutionQuality

ExecutionQuality:
  ticker:          str
  side:            str
  execution_price: float
  vwap:            float
  difference:      float
  basis_points:    float
  favourable:      bool
```

*Requires Trade Service for execution price, Instrument Service for bars, and Analytics Service `vwap` before this comparison can run.*

---

### 4.3 Reasoning Notes

Because the Analytics Service is stateless, the agent must always make at least two tool calls to answer a volatility or momentum question: one to `get_ohlcv_history` on the Instrument Service, then one to the relevant Analytics tool. This is the key cross-service reasoning pattern this service is designed to test.

---

## 5. Agent Prompt Examples for Multi-Stage Reasoning

These prompts are designed to demonstrate that `gofr-agent` can discover, compose, and sequence MCP tools across service boundaries. Each example includes the intended reasoning path so integration tests can assert the minimum service/tool coverage.

### Example 1: Portfolio Risk Snapshot

**Prompt:** "For Meridian Capital, list each current holding, its spot market value, 20-day annualised volatility, and whether the price is above or below its 20-day moving average."

**Expected reasoning path:**

1. `clients.client_lookup("Meridian Capital")`
2. `clients.get_holdings(client_id="C001")`
3. For each holding ticker: `instruments.get_spot_price`, `instruments.get_ohlcv_history`
4. For each bar set: `analytics.position_market_value`, `analytics.historical_volatility`, `analytics.price_momentum`
5. Compose a table grouped by ticker with quantity, market value, volatility, and momentum signal.

### Example 2: Mandate-Aware Trade Candidate

**Prompt:** "Can Apex Fund short Barclays, and has it traded Barclays before? Include the relevant market code and any mandate reason."

**Expected reasoning path:**

1. `clients.client_lookup("Apex Fund")`
2. `instruments.instrument_lookup("Barclays")`
3. `instruments.get_market_codes(ticker="BARC")`
4. `clients.get_mandate_document(client_id="C002")` or `clients.search_mandate_text(client_id="C002", query_terms=["short", "US", "UK", "European"])`
5. Agent extracts the semantic rule: Apex permits short sales only for listed US cash equities and excludes UK or European listed equities.
6. `trades.get_trades(client_id="C002", ticker="BARC")` or `trades.get_trade_summary(client_id="C002", ticker="BARC")`
7. Answer with allowed/not allowed, cited mandate text, relevant market code, and any prior trade evidence.

### Example 3: Watchlist Activity and Execution Quality

**Prompt:** "For every instrument on Blue Ridge Partners' watchlist, show whether any client traded it in the last 60 days and compare the average execution price to the period VWAP."

**Expected reasoning path:**

1. `clients.client_lookup("Blue Ridge Partners")`
2. `clients.get_watchlist(client_id="C003")`
3. For each watched ticker: `trades.list_clients_traded_instrument(ticker, from_date, to_date)`
4. For each active client/ticker pair: `trades.get_average_execution_price(client_id, ticker, from_date, to_date)`
5. For each ticker: `instruments.get_ohlcv_history(ticker, from_date, to_date)` then `analytics.vwap(ticker, bars)`
6. For each execution summary: `analytics.compare_execution_to_vwap(ticker, side, execution_price, vwap)`
7. Summarise active clients, average execution, VWAP, and favourable/unfavourable execution.

### Example 4: Trade Date Context

**Prompt:** "For Apex Fund's most recent NVDA trade, was the execution price inside that day's high-low range, and what was the 20-day volatility as of that date?"

**Expected reasoning path:**

1. `clients.client_lookup("Apex Fund")`
2. `instruments.instrument_lookup("NVDA")`
3. `trades.get_last_trade(client_id="C002", ticker="NVDA")`
4. `instruments.get_price_on_date(ticker="NVDA", date=last_trade.trade_date)`
5. `instruments.get_ohlcv_history(ticker="NVDA", from_date=<20+ day lookback>, to_date=last_trade.trade_date)`
6. `analytics.historical_volatility(ticker="NVDA", bars, window=20)`
7. Answer with trade details, high-low validation, and volatility.

### Example 5: Cross-Client Concentration and Liquidity

**Prompt:** "Which clients currently hold Apple, what is each position worth at spot, and how large is each position relative to the last 30 days of average daily volume?"

**Expected reasoning path:**

1. `instruments.instrument_lookup("Apple")`
2. `clients.get_clients_holding(ticker="AAPL")`
3. For each client: `clients.get_holding(client_id, ticker="AAPL")`
4. `instruments.get_spot_price(ticker="AAPL")`
5. `instruments.get_volume_history(ticker="AAPL", from_date, to_date)`
6. `analytics.position_market_value(client_id, ticker, quantity, spot_price, currency)`
7. Agent computes average daily volume and position-as-days-volume from returned quantities and volumes.

---

## 6. Implementation Notes

### 6.1 File Layout

```
tests/
  fixtures/
    mcp_services/
      __init__.py
      _data_loader.py     # shared CSV loading helpers
      instruments.py      # FastMCP instance; loads data from data/
      clients.py          # FastMCP instance; loads data from data/
      trades.py           # FastMCP instance; loads data from data/
      analytics.py        # FastMCP instance (stateless, no data files)
      conftest.py         # session-scoped fixtures: start all four servers,
                          # expose URLs, build agent config pointing at them
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
```

### 6.2 Server Lifecycle

Each service follows the same `_UvicornThread` pattern used by `mock_mcp_server.py`: a daemon thread hosting uvicorn on a dynamically assigned free port. A session-scoped pytest fixture starts all four servers before any test runs and shuts them down after the session.

### 6.3 Determinism

Data is loaded from CSV files at module import time into module-level dicts (keyed for O(1) lookup). No randomness, no external network I/O at runtime. Any test that calls the agent with a fixed question must get the same answer every run. To change the universe, edit the CSVs and re-run — no Python changes required.

### 6.4 Auth Handling in Services

Each FastMCP tool handler receives the HTTP request context and extracts the `Authorization` header. A shared helper `_require_bearer(request) -> str` raises an MCP `401` error if the header is absent or the token is empty, otherwise returns the raw token string. The token is not validated further. This helper lives in `_data_loader.py` and is imported by all four service modules.

### 6.5 Data Consistency Constraints

- Every ticker referenced in holdings, watchlists, or trades must exist in the Instrument Service.
- Every `client_id` referenced in holdings, watchlists, or trades must exist in the Client Service.
- Trade prices must fall within the OHLCV high/low band for the trade date.
- Net holdings implied by the trade blotter need not match the holdings snapshot — the holdings snapshot represents an external custodian view and may include transfers not captured in the blotter. Tests should not assert cross-service balance equality unless that is the specific scenario under test.

### 6.6 Cross-Service Integration Tests

The integration test file (`tests/integration/test_reasoning_integration.py`) should cover at a minimum:

| Test | Services involved | Assertion |
|---|---|---|
| Spot price lookup | instruments | correct price returned |
| Holdings for client | clients | correct ticker list and quantities |
| Mandate text retrieval | clients | correct mandate document text and excerpts returned |
| Trades for client+instrument | trades | correct trade records |
| Realised P&L calculation | trades | correct FIFO P&L value |
| Volatility requires two hops | instruments + analytics | agent calls `get_ohlcv_history` then `historical_volatility` |
| Holdings + vol | clients + instruments + analytics | agent fans out from holdings list to vol per instrument |
| Watchlist + trade history | clients + trades | agent fans out from watchlist to trades per ticker |
| Mandate + instrument exchange | clients + instruments | agent resolves exchange MIC, reads written mandate text, and semantically infers whether the candidate trade is permitted |
| Full cross-service narrative | all four | a single `ask` question requires ≥4 tool calls across ≥3 services |
