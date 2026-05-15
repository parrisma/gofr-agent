# gofr-agent Specification

> **Status:** Draft v0.2 — open questions resolved  
> **Port allocation:** `GOFR_AGENT_MCP=8090`, `GOFR_AGENT_MCPO=8091`, `GOFR_AGENT_WEB=8092`  
> **Port registration:** to be added to `gofr-common/config/gofr_ports.env` and `ports.py`

---

## 1. Purpose

`gofr-agent` is an MCP server (Streamable HTTP transport) that acts as an **AI reasoning layer over a configurable set of downstream MCP services**.

At startup it:
1. Connects to a declared list of downstream MCP servers.
2. Discovers each server's tools dynamically via the MCP `tools/list` protocol call.
3. Registers those tools with a [pydantic-ai](https://docs.pydantic.ai/) `Agent` as callable functions.

At runtime it exposes a single high-level MCP tool — `ask` — that accepts a natural-language question, runs the pydantic-ai agent (which may call any combination of downstream tools in a multi-step reasoning loop), and returns a structured answer.

---

## 2. High-Level Architecture

```
User / LLM Client ×M (concurrent)
       │  MCP (Streamable HTTP)
       ▼
┌────────────────────────────────────────────────┐
│              gofr-agent                        │
│  ┌────────────────────────────────────────┐    │
│  │  ASGI (uvicorn, async event loop)      │    │  ← handles M concurrent HTTP requests
│  │  MCP Streamable HTTP Server            │    │
│  └───────────────┬────────────────────────┘    │
│                  │ one asyncio Task per ask()  │
│  ┌───────────────▼────────────────────────┐    │
│  │  pydantic-ai Agent  (shared, stateless)│    │  ← agent.run_stream() isolated per call
│  │  agent.run_stream(messages=history)    │    │
│  └───────────────┬────────────────────────┘    │
│                  │ concurrent tool calls       │
│  ┌───────────────▼────────────────────────┐    │
│  │  SessionPool  (per downstream service) │    │  ← pool of ClientSessions; one checked
│  │  asyncio.Semaphore gates pool access   │    │    out per tool call, returned after
│  └────────────────────────────────────────┘    │
└────────────────────────────────────────────────┘
       │  MCP (Streamable HTTP, pool connections)
       ▼
┌────────────┐  ┌────────────┐  ┌────────────┐
│ gofr-plot  │  │  gofr-iq   │  │ gofr-doc   │  …
└────────────┘  └────────────┘  └────────────┘
```

### Concurrency model

`gofr-agent` is **fully async** (asyncio + ASGI). The event loop is never blocked:

| Layer | Concurrency mechanism |
|---|---|
| HTTP / MCP server | uvicorn ASGI — handles M simultaneous connections |
| `ask` handler | Each call runs as an independent `asyncio.Task`; no shared mutable state |
| pydantic-ai Agent | Single shared `Agent` instance — `run_stream()` is stateless and re-entrant |
| Session history | Per-session `asyncio.Lock` guards message-history reads/writes |
| Downstream MCP calls | `SessionPool` per service — checked-out sessions serialise per connection; parallel calls draw from the pool concurrently |
| Session TTL sweep | Background `asyncio.Task`, not a thread |

---

## 3. Downstream Service Configuration

Downstream MCP servers are declared at startup. Configuration supports two mechanisms (evaluated in order):

### 3.1 Environment / `.env` file (simple cases)

```
GOFR_AGENT_SERVICES=plot,iq,doc
GOFR_AGENT_PLOT_URL=http://localhost:8050/mcp
GOFR_AGENT_IQ_URL=http://localhost:8080/mcp
GOFR_AGENT_DOC_URL=http://localhost:8040/mcp
# Optional JWT tokens per service
GOFR_AGENT_PLOT_TOKEN=<jwt>
GOFR_AGENT_IQ_TOKEN=<jwt>
```

### 3.2 YAML services manifest (recommended for larger deployments)

`--services-file path/to/services.yml`

```yaml
# services.yml
services:
  - name: plot
    url: http://localhost:8050/mcp
    token_env: GOFR_AGENT_PLOT_TOKEN   # env var holding the JWT
    description: "Graph rendering service"
    enabled: true

  - name: iq
    url: http://localhost:8080/mcp
    token_env: GOFR_AGENT_IQ_TOKEN
    description: "Document Q&A / knowledge base"
    enabled: true

  - name: doc
    url: http://localhost:8040/mcp
    token_env: GOFR_AGENT_DOC_TOKEN
    description: "Document ingestion and retrieval"
    enabled: true
```

**Schema** (validated with pydantic at startup):

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | str | yes | Unique slug used as tool namespace prefix |
| `url` | AnyHttpUrl | yes | Streamable HTTP endpoint |
| `token_env` | str \| None | no | Env var name containing the Bearer token |
| `description` | str | no | Injected into system prompt for tool context |
| `enabled` | bool | yes (default true) | Allows disabling without removing entry |
| `timeout_s` | float | no (default 30) | Per-request HTTP timeout |

---

## 4. Tool Discovery

On startup, for each enabled service, `gofr-agent`:

1. Opens a **`SessionPool`** of `GOFR_AGENT_SESSION_POOL_SIZE` (default: 3) long-lived MCP `ClientSession` connections per service using `mcp.client.streamable_http.streamablehttp_client`.
2. Calls `list_tools()` on one session to get the service's tool catalogue.
3. For each discovered tool, generates a **pydantic-ai tool wrapper** that:
   - Takes the tool's declared input schema as a typed pydantic model.
   - Checks out an available session from the pool (via `asyncio.Semaphore`), calls `session.call_tool(tool_name, args)`, then returns the session to the pool.
   - Is namespaced as `{service_name}__{tool_name}` to avoid collisions.
4. Registers all wrappers with the pydantic-ai `Agent`.

Tool discovery runs at startup for all services in the manifest. It also runs on-demand when a new MCP service is registered at runtime via the `register_service` MCP tool — no restart required. The `ServiceRegistry` keeps the pydantic-ai `Agent` updated after each registration by rebuilding the tool set.

**Session pooling** ensures that concurrent `ask` calls can make downstream tool calls simultaneously without queuing behind each other. If all pool slots are busy the tool call awaits a free slot (non-blocking to the event loop). The pool maintains each connection with a reconnect loop and exponential back-off.

---

## 5. MCP Tools Exposed

### 5.1 `ask`

The primary interface.

**Input:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `question` | str | yes | Natural-language question or instruction |
| `session_id` | str \| None | no | Opaque ID to continue a prior conversation; omit to start a new session |
| `context` | str \| None | no | Optional caller-supplied context appended to system prompt |
| `max_steps` | int | no (default 10) | Hard cap on reasoning iterations |
| `model_override` | str \| None | no | Override configured LLM (e.g., `openai:gpt-4o`) |

**Output:** streamed via MCP notifications (one notification per reasoning step) then a final `TextContent` JSON result:

```json
{
  "session_id": "ses_abc123",
  "answer": "...",
  "steps": [
    { "step": 1, "type": "tool_call",   "tool": "plot__render_graph", "args": {...} },
    { "step": 1, "type": "tool_result", "tool": "plot__render_graph", "result": "..." },
    { "step": 2, "type": "tool_call",   "tool": "iq__search_docs",    "args": {...} },
    { "step": 2, "type": "tool_result", "tool": "iq__search_docs",    "result": "..." }
  ],
  "model": "openai:gpt-4o-mini",
  "tokens_used": 1234
}
```

Each reasoning step is also emitted as an MCP `notifications/message` so that streaming-aware clients (e.g. the CLI tool) can display progress in real time without waiting for the final answer. See §7 for details.

### 5.2 `reset_session`

Clears conversation history for a session.

**Input:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `session_id` | str | yes | Session to clear |

**Output:** `{ "status": "cleared", "session_id": "..." }`

### 5.3 `register_service`

Registers a new downstream MCP service at runtime without restarting the agent. Triggers tool discovery immediately and rebuilds the pydantic-ai tool set.

**Input:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | str | yes | Unique slug (used as tool namespace prefix) |
| `url` | str | yes | Streamable HTTP endpoint |
| `token` | str \| None | no | Bearer token for the downstream service |
| `description` | str \| None | no | Injected into system prompt |

**Output:** `{ "status": "registered", "name": "...", "tools_discovered": 5 }`

### 5.4 `list_services`

Returns the currently connected downstream services and their available tools.

**Input:** none

**Output:** JSON list of `{ name, url, status, tools: [{ name, description }] }`

### 5.5 `ping`

Standard health check returning timestamp and version (consistent with other gofr services).

### 5.6 `refresh_services` *(admin)*

Re-runs tool discovery against all registered services and rebuilds the agent tool set. Requires auth token if auth is enabled.

---

## 6. Session Management

### 6.1 Session model

Each `ask` call either creates a new session (when `session_id` is omitted or unknown) or continues an existing one. A new `session_id` is returned in every response.

Sessions are stored in-process in a `SessionStore` (a dict keyed by `session_id`). Each session holds:

```python
@dataclass
class Session:
    session_id: str
    messages: list[ModelMessage]   # pydantic-ai message history
    lock: asyncio.Lock             # guards concurrent access to this session
    created_at: datetime
    last_active: datetime
```

`messages` is the pydantic-ai `MessageHistory` object passed to `Agent.run_stream(..., message_history=...)` on subsequent turns, giving the LLM full context of the prior conversation.

Each `ask` call acquires the session's `lock` before reading or writing `messages`. This prevents two concurrent requests on the same `session_id` from corrupting history. The lock is held only for the duration of the history read (before the agent run) and the history write (after), not for the entire LLM reasoning loop, so it does not block unrelated sessions.

### 6.2 Session TTL

Sessions expire after `GOFR_AGENT_SESSION_TTL_MINUTES` of inactivity (default: 60). A background task sweeps expired sessions every minute.

### 6.3 Reset

`reset_session` (MCP tool §5.2) clears the message history for a session. The `session_id` is preserved but the conversation starts fresh.

### 6.4 Persistence

v1 sessions are in-memory only. A restart loses all session history. Disk persistence is a future consideration.

---

## 7. Streaming & Reasoning Visibility

### 7.1 Mechanism

`agent.run_stream()` is used instead of `agent.run()`. As each reasoning step completes, the agent emits an MCP `notifications/message` notification containing a JSON step object:

```json
{
  "type": "step",
  "step": 2,
  "kind": "tool_call",
  "tool": "iq__search_docs",
  "args": { "query": "Q3 revenue" }
}
```

```json
{
  "type": "step",
  "step": 2,
  "kind": "tool_result",
  "tool": "iq__search_docs",
  "result": "Revenue was $42M (see http://gofr-iq/results/abc123)"
}
```

The final message in the stream is the complete answer JSON (§5.1).

### 7.2 Parallel tool calls

pydantic-ai parallel tool dispatch is **enabled**. When the LLM issues multiple tool calls in one step, they are awaited concurrently. Each individual tool call/result pair is still emitted as a separate notification so the client sees granular progress.

### 7.3 Tool result size limit

Downstream tool results are truncated to `GOFR_AGENT_TOOL_RESULT_MAX_CHARS` (default: 4000) before being fed to the LLM. A truncation notice is appended:
`[... result truncated at 4000 chars. Full result available at: <url if present>]`

This is appropriate because the downstream MCPs are session-based and return links (URLs) to large artefacts rather than embedding them inline.

### 7.4 CLI tool

A command-line tool (`scripts/ask.py` or `python -m app.cli`) connects to the agent's MCP endpoint, issues an `ask` call, and renders the streaming notifications to the terminal in real time:

```
$ gofr-agent ask "Plot revenue for Q1-Q4 and summarise the trend"

[session: ses_abc123]
  step 1 → plot__render_graph (title="Revenue Q1-Q4", ...)
  step 1 ← http://gofr-plot/download/guid123
  step 2 → iq__search_docs (query="revenue trend Q1-Q4")
  step 2 ← Revenue grew 18% YoY driven by …

Answer: Revenue grew 18% year-on-year. A chart has been rendered at
        http://gofr-plot/download/guid123. The strongest quarter was Q3 …
```

The CLI supports `--session SESSION_ID` to continue a prior conversation and `--reset SESSION_ID` to clear one.

---

## 8. pydantic-ai Integration

### 8.1 Agent construction

```python
from pydantic_ai import Agent

agent = Agent(
    model=settings.llm_model,          # e.g. "openai:gpt-4o-mini"
    system_prompt=build_system_prompt(service_descriptors),
    tools=discovered_tool_wrappers,    # built from MCP tool discovery
)
```

### 8.2 Tool wrapper pattern

Each downstream MCP tool becomes a pydantic-ai `Tool`:

```python
from pydantic_ai import Tool, RunContext

def make_tool(session: ClientSession, svc_name: str, mcp_tool: MCPTool) -> Tool:
    InputModel = build_pydantic_model(mcp_tool.inputSchema)

    async def call(ctx: RunContext, **kwargs) -> str:
        result = await session.call_tool(mcp_tool.name, kwargs)
        return result.content[0].text  # or serialised form

    return Tool(
        name=f"{svc_name}__{mcp_tool.name}",
        description=mcp_tool.description or "",
        function=call,
        takes_ctx=True,
    )
```

### 8.3 System prompt

The system prompt is assembled from:
- A fixed preamble describing the agent's role.
- Per-service descriptors (name + description + tool list summary).
- Optional caller-supplied `context` from the `ask` call.

### 8.4 LLM provider

Configured via `GOFR_AGENT_LLM_MODEL` (default: `openai:gpt-4o-mini`). pydantic-ai supports OpenAI, Anthropic, Gemini, Groq, Mistral, Ollama, and OpenAI-compatible endpoints (e.g. OpenRouter) out of the box. API key sourced from Vault (same pattern as gofr-iq) with env-var override `GOFR_AGENT_OPENROUTER_API_KEY`.

---

## 9. Authentication

Follows the same JWT-based auth pattern as `gofr-plot` and `gofr-iq`:

- `GOFR_AGENT_JWT_SECRET` — shared secret for token signing/validation.
- `--no-auth` flag for development.
- Auth middleware validates `Authorization: Bearer <token>` on every MCP call.
- Token issuance is out-of-scope for this service (delegated to gofr-common auth machinery).

---

## 10. Configuration Reference

| Env Var | Default | Notes |
|---|---|---|
| `GOFR_AGENT_MCP_PORT` | `8090` | MCP Streamable HTTP port |
| `GOFR_AGENT_MCPO_PORT` | `8091` | MCPO wrapper port |
| `GOFR_AGENT_WEB_PORT` | `8092` | Reserved for future web UI |
| `GOFR_AGENT_HOST` | `0.0.0.0` | Bind address |
| `GOFR_AGENT_LLM_MODEL` | `openai:gpt-4o-mini` | pydantic-ai model string |
| `GOFR_AGENT_OPENROUTER_API_KEY` | — | Override; otherwise read from Vault |
| `GOFR_AGENT_JWT_SECRET` | — | Required unless `--no-auth` |
| `GOFR_AGENT_SERVICES` | — | Comma-separated service names (alt. to YAML) |
| `GOFR_AGENT_MAX_STEPS` | `10` | Default reasoning step cap |
| `GOFR_AGENT_SESSION_TTL_MINUTES` | `60` | Idle session expiry |
| `GOFR_AGENT_TOOL_RESULT_MAX_CHARS` | `4000` | Truncation limit per tool result |
| `GOFR_AGENT_SESSION_POOL_SIZE` | `3` | MCP ClientSessions per downstream service |
| `GOFR_AGENT_LOG_LEVEL` | `INFO` | DEBUG / INFO / WARNING / ERROR |

---

## 11. Proposed File Structure

Mirrors `gofr-plot` / `gofr-iq` layout:

```
gofr-agent/
├── app/
│   ├── __init__.py
│   ├── config.py                  # GofrAgentConfig (pydantic settings)
│   ├── settings.py                # re-exports gofr-common Settings with GOFR_AGENT prefix
│   ├── main_mcp.py                # CLI entrypoint → starts MCP server
│   ├── main_mcpo.py               # MCPO wrapper entrypoint (optional)
│   ├── mcp_server/
│   │   ├── __init__.py
│   │   └── mcp_server.py          # MCP tool registration (ask, reset_session, register_service, ...)
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── agent.py               # pydantic-ai Agent construction + run_stream()
│   │   ├── tool_factory.py        # MCP-tool → pydantic-ai Tool conversion + result truncation
│   │   └── system_prompt.py       # System prompt builder
│   ├── sessions/
│   │   ├── __init__.py
│   │   └── store.py               # SessionStore: in-memory dict + TTL sweep
│   ├── services/
│   │   ├── __init__.py
│   │   ├── registry.py            # ServiceRegistry: load config, manage SessionPools
│   │   ├── pool.py                # SessionPool: asyncio.Semaphore + checked-out session logic
│   │   ├── discovery.py           # Tool discovery + reconnect loop
│   │   └── models.py              # ServiceConfig pydantic models
│   ├── cli/
│   │   ├── __init__.py
│   │   └── ask.py                 # CLI tool: streams ask responses to terminal
│   ├── auth/                      # thin re-export of gofr-common auth
│   ├── logger/                    # thin re-export of gofr-common logger
│   └── exceptions/
├── data/
├── docs/
│   └── SPEC.md                    # this file
├── docker/
├── lib/
│   └── gofr-common/               # git submodule
├── scripts/
├── tests/
├── pyproject.toml
└── services.yml.example
```

---

## 12. Key Dependencies

| Package | Purpose |
|---|---|
| `mcp>=1.26.0` | MCP protocol (server + client) |
| `pydantic-ai>=0.0.54` | Agent framework + streaming tool dispatch |
| `pydantic>=2.0` | Config validation, tool schema generation |
| `httpx>=0.27` | Async HTTP for MCP client connections |
| `typer>=0.20.0` | CLI tool (`app/cli/ask.py`) |
| `fastapi` / `uvicorn` | ASGI host for Streamable HTTP (via gofr-common) |
| `PyJWT` | Auth token validation (via gofr-common) |

---

## 13. Startup Sequence

```
1. Parse CLI args / load env
2. Validate GofrAgentConfig (ports, LLM model, JWT secret)
3. Load services manifest (YAML or env)
4. For each enabled service:
   a. Open SessionPool of GOFR_AGENT_SESSION_POOL_SIZE long-lived ClientSessions
   b. Call list_tools() on one session → store catalogue
   c. Build pydantic-ai Tool wrappers (namespaced svc__tool, pool-aware)
   d. Start reconnect background tasks (one per pool slot)
5. Construct pydantic-ai Agent with all tools + system prompt
6. Start SessionStore TTL sweep background task
7. Start MCP Streamable HTTP server on GOFR_AGENT_MCP_PORT
8. Log service summary (services connected, tool count, session TTL)
```

---

## 14. Error Handling

| Scenario | Behaviour |
|---|---|
| Downstream service unreachable at startup | Log warning, skip service, continue (partial degradation) |
| Downstream service disconnects at runtime | Reconnect loop retries each pool slot with back-off; other slots continue serving; tool calls fail gracefully if all slots are down |
| All pool slots busy for a service | Tool call awaits a free slot (async, does not block the event loop or other sessions) |
| Downstream tool call fails during `ask` | Return error text to agent; agent may retry or report to user |
| Tool result exceeds `TOOL_RESULT_MAX_CHARS` | Truncate and append notice; URL preserved if present |
| LLM API key missing / invalid | Fatal startup error |
| `max_steps` reached | Return partial answer with notice |
| Unknown `session_id` | Create new session, return new `session_id` |
| Auth token invalid | Return MCP error (same as other gofr services) |

---

## 15. Resolved Decisions

| # | Question | Decision |
|---|---|---|
| 1 | MCP ClientSession lifecycle | **Long-lived** — held open per service, reconnect loop with back-off |
| 2 | Streaming / reasoning visibility | **Stream per step** via MCP `notifications/message`; CLI renders in real time |
| 3 | Tool result size | **Truncate** at `GOFR_AGENT_TOOL_RESULT_MAX_CHARS` (default 4000); preserve any URL |
| 4 | Parallel tool calls | **Enabled**; each call/result still emitted as individual notification |
| 5 | Web UI | **Out of scope for v1**; CLI tool only |
| 6 | Conversation history | **Session-based** with `session_id`; in-memory with TTL; `reset_session` tool |
| 7 | Tool namespacing | **`{service_name}__{tool_name}`** — tools scoped to the MCP server that offers them |
| 8 | Port registration | **Register in gofr-common** — add `GOFR_AGENT` to `gofr_ports.env` and `ports.py` |
