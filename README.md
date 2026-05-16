# gofr-agent

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![uv](https://img.shields.io/badge/package%20manager-uv-purple)](https://github.com/astral-sh/uv)

A [pydantic-ai](https://github.com/pydantic/pydantic-ai) **MCP Streamable-HTTP reasoning agent** that orchestrates downstream MCP services.

gofr-agent exposes a single MCP endpoint.  Clients (Claude Desktop, `mcpo`,
the bundled CLI) send natural-language questions; the agent picks the right
tools from its connected downstream services and returns a grounded answer.

---

## Table of contents

- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Services manifest](#services-manifest)
- [Results hub](#results-hub)
- [MCP tools](#mcp-tools)
- [CLI](#cli)
- [Development](#development)

---

## Architecture

```
Client (Claude / mcpo / CLI)
        │  MCP Streamable-HTTP
        ▼
  ┌─────────────────────────┐
  │       gofr-agent        │
  │  FastMCP  ←→  GofrAgent │   pydantic-ai reasoning
  └──────┬──────────────────┘
         │  MCP (per service pool)
    ┌────┴────────────────────┐
    │   Downstream services   │
    │  rag / sandbox / …      │
    └─────────────────────────┘
```

Key components:

| Module | Responsibility |
|--------|----------------|
| `app/mcp_server/` | FastMCP server, tool definitions |
| `app/agent/` | pydantic-ai `Agent`, tool factory, system prompt |
| `app/services/` | Service registry, session pool, tool discovery |
| `app/sessions/` | In-memory session store with TTL sweep |
| `app/cli/` | Typer CLI (`ask`) |
| `app/config.py` | `GofrAgentConfig` — all settings |

---

## Quick start

```bash
# 1. Clone and enter the repo
git clone https://github.com/parrisma/gofr-agent.git && cd gofr-agent

# 2. Install dependencies (uv is the package manager)
uv sync

# 3. Copy and edit the services manifest
cp services.yml.example services.yml
$EDITOR services.yml

# 4. Start the server
#    Any OpenAI-compatible provider works; OpenRouter example:
GOFR_AGENT_LLM_MODEL=openai:deepseek/deepseek-v4-pro \
OPENROUTER_API_KEY=sk-or-... \
uv run python -m app.main_mcp --services-file services.yml

# 5. Ask a question via the CLI
GOFR_AGENT_TOKEN=dev-admin-token \
uv run python -m app.cli.ask "What tools are available?"
```

The server listens on **port 8090** by default.

---

## Configuration

`GofrAgentConfig.from_env()` is the single configuration path. Settings use the
`GOFR_AGENT_` prefix.

| Env var | Default | Description |
|---------|---------|-------------|
| `GOFR_AGENT_HOST` | `0.0.0.0` | Bind host |
| `GOFR_AGENT_MCP_PORT` | `8090` | MCP server port |
| `GOFR_AGENT_MCPO_PORT` | `8091` | OpenAI-compatible proxy port |
| `GOFR_AGENT_SERVICES_FILE` | unset | Optional services manifest path |
| `GOFR_AGENT_HUB_ENABLED` | `false` | Enable the built-in results hub for descriptor handoff |
| `GOFR_AGENT_HUB_URL` | unset | Public MCP URL other services use to call this agent's hub tools |
| `GOFR_AGENT_HUB_DEFAULT_TTL_SECONDS` | `3600` | Default descriptor TTL, capped per stored result |
| `GOFR_AGENT_HUB_MAX_PAYLOAD_BYTES` | `524288` | Maximum JSON payload size accepted by `_store_result` |
| `GOFR_AGENT_HUB_MAX_RESULTS` | `256` | Maximum in-memory hub records kept at once |
| `GOFR_AGENT_HUB_PROTOCOL_VERSION` | `1` | Reserved protocol version for hub registration and descriptors |
| `GOFR_AGENT_LLM_MODEL` | `openai:gpt-4o-mini` | Default pydantic-ai model |
| `GOFR_AGENT_AGENT_TIMEOUT_SECONDS` | `120` | Wall-clock timeout for a single `ask` run |
| `GOFR_AGENT_MAX_STEPS` | `10` | Default step limit when callers omit `max_steps` |
| `GOFR_AGENT_MAX_STEPS_HARD_CAP` | `50` | Upper bound for caller-provided `max_steps` |
| `GOFR_AGENT_MAX_QUESTION_CHARS` | `8000` | Input question size cap |
| `GOFR_AGENT_MAX_CONTEXT_CHARS` | `16000` | Caller-supplied context size cap |
| `GOFR_AGENT_MAX_EVENT_PAYLOAD_CHARS` | `4000` | Reasoning-event payload cap |
| `GOFR_AGENT_MAX_RESPONSE_STEPS` | `200` | Final `steps` array cap |
| `GOFR_AGENT_MAX_SESSIONS` | `1000` | Maximum in-memory sessions |
| `GOFR_AGENT_MAX_MESSAGES_PER_SESSION` | `100` | Recent raw-message window before compaction |
| `GOFR_AGENT_SESSION_TTL_MINUTES` | `60` | Session expiry window |
| `GOFR_AGENT_SESSION_SWEEP_INTERVAL_SECONDS` | `60` | Session sweep cadence |
| `GOFR_AGENT_TOOL_RESULT_MAX_CHARS` | `4000` | Downstream tool-result truncation limit |
| `GOFR_AGENT_TOOL_RETRY_ATTEMPTS` | `2` | Retries for transient downstream tool failures |
| `GOFR_AGENT_SESSION_POOL_SIZE` | `3` | Concurrent downstream sessions per service |
| `GOFR_AGENT_DYNAMIC_REGISTRATION_ENABLED` | `false` | Enable runtime `register_service` |
| `GOFR_AGENT_ALLOWED_SERVICE_HOSTS` | empty | Exact or wildcard allow-list for dynamic registration |
| `GOFR_AGENT_ALLOWED_MODELS` | empty | Allow-list for `model_override` |
| `GOFR_AGENT_LOG_LEVEL` | `INFO` | Logging level |

---

## Services manifest

Copy `services.yml.example` to `services.yml` and fill in your services:

```yaml
services:
  - name: instruments
    url: http://gofr-instruments:8100/mcp
    description: Instrument metadata and OHLCV history
    token_env: INSTRUMENTS_MCP_TOKEN
    hub_callback_token_env: INSTRUMENTS_HUB_CALLBACK_TOKEN
    enabled: true
```

Use Docker service names or other routable hostnames reachable from the
`gofr-agent` container. Do not use `localhost` or `127.0.0.1` for service-to-
service MCP traffic.

`hub_callback_token_env` is optional and is needed only for services that
publish to or fetch from the results hub. Keep callback credentials in env vars
rather than inline secrets.

Services can also be registered at runtime via the `register_service` MCP tool
when `GOFR_AGENT_DYNAMIC_REGISTRATION_ENABLED=true` and the target host matches
`GOFR_AGENT_ALLOWED_SERVICE_HOSTS`.

## Results hub

When `GOFR_AGENT_HUB_ENABLED=true`, `gofr-agent` also acts as a process-local
results hub for descriptor handoff between MCP services.

- Producer services call `_store_result` and return only a descriptor such as
  `{"kind":"gofr.result_ref", ...}` to the model.
- Consumer services accept descriptor-enabled arguments and fetch the
  authoritative payload through `_get_result` or `_describe_result`.
- The model and UI should treat descriptors as internal references, not as
  user-facing payloads. Large JSON payloads stay out of model context and out
  of reasoning-event streams.
- Reserved protocol tools `_register_results_hub`, `_store_result`,
  `_get_result`, and `_describe_result` are not exposed in the model-facing
  tool list.
- `list_services` reports safe hub capability metadata
  (`supports_results_hub`, `can_publish_results`, `can_consume_results`,
  `result_types`, `registration_error`) but never returns bearer tokens or
  callback credentials.

---

## MCP tools

gofr-agent exposes these tools over MCP:

| Tool | Description |
|------|-------------|
| `ping` | Health check — returns status, timestamp, version |
| `list_services` | List registered downstream services, their health, tools, and safe hub-capability metadata |
| `ask` | Send a question to the reasoning agent |
| `reset_session` | Clear conversation history for a session |
| `register_service` | Dynamically register a new downstream service |
| `refresh_services` | Re-discover tools for all registered services |

### `ask` parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `question` | `str` | required | The question to answer |
| `session_id` | `str` | auto-generated | Session ID for conversation continuity |
| `context` | `str` | `null` | Extra context prepended to the question |
| `max_steps` | `int` | `10` | Maximum tool-call iterations |
| `model_override` | `str` | `null` | Optional allow-listed model override |

`model_override` is accepted only when the caller has the
`AGENT_MODEL_OVERRIDE` activity and the requested model appears in
`GOFR_AGENT_ALLOWED_MODELS`.

### `ask` response

```json
{
  "session_id": "abc-123",
  "request_id": "req-123",
  "answer": "The answer is …",
  "steps": [
    {"kind": "run_started", "sequence": 1},
    {"kind": "tool_call", "sequence": 3, "service": "svc", "tool": "lookup"},
    {"kind": "tool_result", "sequence": 4, "service": "svc", "tool": "lookup", "ok": true},
    {"kind": "run_completed", "sequence": 5}
  ],
  "model": "openai:gpt-4o-mini",
  "tokens_used": 142
}
```

`steps` is derived from the same live reasoning event stream sent over MCP
logging notifications. Tool-using runs and summary-compaction runs produce
non-empty `steps`.

---

## CLI

```bash
# Ask a question (auto-generates a session ID)
uv run python -m app.cli.ask "What is the capital of France?"

# Continue a conversation
uv run python -m app.cli.ask --session abc-123 "What about Germany?"

# Final answer only
uv run python -m app.cli.ask --quiet "What is the capital of France?"

# Verbose reasoning trace with tool arguments and summaries
uv run python -m app.cli.ask --verbose "What is the capital of France?"

# Emit JSON with both streamed events and the final response
uv run python -m app.cli.ask --format json "What is the capital of France?"

# Reset a session
uv run python -m app.cli.ask --reset abc-123

# Point at a custom server
uv run python -m app.cli.ask --url http://myserver:8090/mcp "Hello"
```

Default CLI mode renders compact reasoning events when the server emits them,
then prints the final answer. `--quiet` suppresses event output and metadata.
`--verbose` expands the trace with thinking labels, tool arguments, and bounded
tool-result summaries. `--format json` prints `{"events": [...], "response": {...}}`.
The CLI consumes MCP `notifications/message` log events and filters for the
`gofr-agent.reasoning` payloads.

### Interactive fixture chat

`scripts/fixture_chat.py` is a one-command launcher for manual testing
against the bundled Docker Swarm fixture stack (`instruments`, `clients`,
`trades`, `analytics`). It deploys the stack, starts a local gofr-agent
MCP server wired against all four services, and opens a REPL.

Requires `OPENROUTER_API_KEY` in the environment.

```bash
export OPENROUTER_API_KEY=sk-or-...

# Start the REPL with a higher tool-call ceiling for multi-service questions
uv run python scripts/fixture_chat.py --max-steps 25

# Start the REPL with a more descriptive reasoning trace
uv run python scripts/fixture_chat.py --max-steps 25 --verbose
```

REPL commands: `:quit`, `:exit`, `:reset`. Use `--once "question"` for a
one-shot run, `--keep-stack` to leave the fixtures running on exit, and
`--skip-stack` if they are already deployed.

#### Example: cross-service reasoning question

Paste this at the `gofr>` prompt to exercise all four downstream
services in a single turn:

> For Meridian Capital, identify their largest equity holding by
> current market value, then summarise their last 5 trades in that
> instrument (date, side, quantity, price), compute the realised P&L
> on those trades and the unrealised P&L on the remaining position
> using the current spot, and finally compare the position's total
> return against the instrument's 30-day analytics (return,
> volatility, max drawdown). Return one paragraph with the client id,
> instrument symbol, holding quantity, spot price, realised P&L,
> unrealised P&L, total return, and a one-sentence comparison to the
> 30-day analytics.

A representative answer (exact figures depend on fixture seed data and
the model in use):

> **C001 (Meridian Capital)** — largest equity holding is **AAPL**
> with **5,000 shares** at a spot price of **$189.45** (market value
> $947,250, per `analytics__position_market_value`). Only two trades
> exist on the blotter for this pair: **(1)** 2026-02-16, BUY 1,000 @
> $182.10; **(2)** 2026-03-23, SELL 500 @ $191.30. The FIFO
> **realised P&L** on the round-trip is **+$4,600.00** (per
> `trades__get_realised_pnl`). Using the average buy price of $182.10
> as the cost basis for the remaining 5,000 shares, the **unrealised
> P&L** is **+$36,750.00** (5,000 × ($189.45 − $182.10)), bringing
> the combined **total return** since inception to approximately
> **+4.54%**. Over the same 30-day window (13 Apr – 13 May 2026),
> AAPL posted a **−1.09%** simple return, **20.1%** annualised
> volatility, and a **−5.29%** max drawdown (peak $189.42 on 28 Apr
> to trough $179.39 on 11 May). While the instrument has drifted
> modestly lower over the past month with a notable drawdown,
> Meridian's position — acquired at a significantly lower cost basis
> — remains comfortably in positive territory, outperforming the
> 30-day benchmark return by roughly 560 basis points.

The same question as a one-shot:

```bash
uv run python scripts/fixture_chat.py --max-steps 25 --once "For Meridian Capital, identify their largest equity holding by current market value, then summarise their last 5 trades in that instrument (date, side, quantity, price), compute the realised P&L on those trades and the unrealised P&L on the remaining position using the current spot, and finally compare the position's total return against the instrument's 30-day analytics (return, volatility, max drawdown). Return one paragraph with the client id, instrument symbol, holding quantity, spot price, realised P&L, unrealised P&L, total return, and a one-sentence comparison to the 30-day analytics."
```

---

## Development

```bash
# Install dependencies
uv sync

# Install the local git pre-commit hooks
uv run pre-commit install

# Run quality gate (lint + type-check + security)
./scripts/run_tests.sh --quality

# Run unit tests
./scripts/run_tests.sh --unit

# Run integration tests (starts in-process mock MCP server)
./scripts/run_tests.sh --integration

# Run the full suite
./scripts/run_tests.sh

# Lint / format
uv run ruff check app tests --fix

# Run pre-commit checks across the repo
uv run pre-commit run --all-files

# Refresh the committed secret-scanner baseline after intentional changes
uv run detect-secrets scan --exclude-files '^\.secrets\.baseline$' . > .secrets.baseline
```

The pre-commit stack blocks obviously sensitive local files by path and filename
and also scans staged content for likely secrets. If you need to document a
template, rename it with a suffix like `.example`, `.sample`, or `.template`
instead of committing a real credential or certificate.

### Port assignments

| Port | Service |
|------|---------|
| 8090 | gofr-agent MCP (Streamable HTTP) |
| 8091 | mcpo OpenAI-compatible proxy |
| 8092 | gofr-agent web UI (future) |
| 8190–8192 | Test ports (mirror of above) |

### OpenRouter

The integration tests and the server both work with [OpenRouter](https://openrouter.ai)
as an OpenAI-compatible provider. Set the following environment variables:

```bash
export OPENROUTER_API_KEY=sk-or-...
export OPENROUTER_MODEL=deepseek/deepseek-v4-pro   # optional override for live tests
```

Run the live integration tests (requires API key):

```bash
OPENROUTER_API_KEY=sk-or-... \
./scripts/run_tests.sh tests/integration/test_openrouter.py -m openrouter
```

---

## Licence

[MIT](LICENSE) © 2026 parrisma
