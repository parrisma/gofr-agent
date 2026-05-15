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

# 4. Start the server (development — no auth)
#    Any OpenAI-compatible provider works; OpenRouter example:
GOFR_AGENT_LLM_MODEL=openai:deepseek/deepseek-v4-pro \
OPENROUTER_API_KEY=sk-or-... \
uv run python -m app.main_mcp --no-auth

# 5. Ask a question via the CLI
uv run python -m app.cli.ask "What tools are available?"
```

The server listens on **port 8090** by default.

---

## Configuration

All settings can be set via environment variables (prefix `GOFR_AGENT_`) or CLI
flags.

| Env var | CLI flag | Default | Description |
|---------|----------|---------|-------------|
| `GOFR_AGENT_HOST` | `--host` | `0.0.0.0` | Bind host |
| `GOFR_AGENT_MCP_PORT` | `--port` | `8090` | Bind port |
| `GOFR_AGENT_JWT_SECRET` | `--jwt-secret` | — | JWT secret (required when auth enabled) |
| `GOFR_AGENT_REQUIRE_AUTH` | `--no-auth` | `true` | Disable JWT auth for dev |
| `GOFR_AGENT_SERVICES_FILE` | `--services-file` | `services.yml` | Path to services manifest |
| `GOFR_AGENT_LLM_MODEL` | `--llm-model` | `openai:deepseek/deepseek-v4-pro` | pydantic-ai model string |
| `GOFR_AGENT_SESSION_POOL_SIZE` | `--pool-size` | `3` | Concurrent connections per service |
| `GOFR_AGENT_SESSION_TTL_MINUTES` | — | `60` | Session expiry |
| `GOFR_AGENT_TOOL_RESULT_MAX_CHARS` | — | `4000` | Truncation limit for tool results |
| `GOFR_AGENT_LOG_LEVEL` | `--log-level` | `INFO` | Logging level |

---

## Services manifest

Copy `services.yml.example` to `services.yml` and fill in your services:

```yaml
services:
  - name: rag
    url: http://localhost:8100/mcp
    description: Internal knowledge base search
    token_env: RAG_MCP_TOKEN   # reads token from this env var
    enabled: true
```

Services can also be registered at runtime via the `register_service` MCP tool.

---

## MCP tools

gofr-agent exposes these tools over MCP:

| Tool | Description |
|------|-------------|
| `ping` | Health check — returns status, timestamp, version |
| `list_services` | List all registered downstream services and their health |
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

### `ask` response

```json
{
  "session_id": "abc-123",
  "answer": "The answer is …",
  "steps": [],
  "model": "openai:gpt-4o-mini",
  "tokens_used": 142
}
```

---

## CLI

```bash
# Ask a question (auto-generates a session ID)
uv run python -m app.cli.ask "What is the capital of France?"

# Continue a conversation
uv run python -m app.cli.ask --session abc-123 "What about Germany?"

# Reset a session
uv run python -m app.cli.ask --reset abc-123

# Point at a custom server
uv run python -m app.cli.ask --url http://myserver:8090/mcp "Hello"
```

---

## Development

```bash
# Install (editable) including gofr-common
uv sync
uv pip install -e lib/gofr-common

# Run quality gate (lint + type-check + security)
uv run python -m pytest tests/code_quality/ -v

# Run unit tests
uv run python -m pytest tests/unit/ -v

# Run integration tests (starts in-process mock MCP server)
uv run python -m pytest tests/integration/ -v

# Run everything with coverage
uv run python -m pytest --cov=app --cov-report=term-missing

# Lint / format
uv run ruff check app tests --fix
```

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
export OPENROUTER_MODEL=deepseek/deepseek-v4-pro   # default used by tests
```

Run the live integration tests (requires API key):

```bash
OPENROUTER_API_KEY=sk-or-... \
uv run python -m pytest tests/integration/test_openrouter.py -v -m openrouter
```

---

## Licence

[MIT](LICENSE) © 2026 parrisma
