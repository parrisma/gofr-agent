# gofr-agent Architecture Overview

Status date: 2026-05-22.

This document is the architecture-oriented companion to
`docs/current_state.md` and `docs/master_specification.md`. It explains how
`gofr-agent` is assembled at runtime, how it interacts with downstream MCP
services, how the optional results hub fits into the request path, and where
the main trust and state boundaries sit today.

## 1. System role

`gofr-agent` is an MCP Streamable HTTP server that sits between MCP clients and
multiple downstream MCP services.

Its job is not to be a data source itself. Its job is to:

1. expose a stable MCP control plane to callers
2. discover tools from registered downstream MCP services
3. turn those discovered tools into pydantic-ai tools
4. run a bounded reasoning loop that can call those tools on the caller's behalf
5. optionally coordinate large-result handoff through the built-in results hub

At a high level, `gofr-agent` is a reasoning orchestrator over MCP, not a
general-purpose API gateway and not a durable workflow engine.

## 2. High-level component model

~~~mermaid
flowchart TD
    Client[MCP client / CLI / UI / proxy] -->|Streamable HTTP /mcp| MCP[FastMCP server]
    MCP --> Auth[Auth + request validation]
    MCP --> Sessions[SessionStore]
    MCP --> Agent[GofrAgent / pydantic-ai]
    MCP --> Health[HTTP /ping and /health]

    Agent --> Registry[ServiceRegistry]
    Registry --> Pools[SessionPool per service]
    Pools --> Discovery[Tool discovery]
    Agent --> ToolWrappers[Generated tool wrappers]
    ToolWrappers -->|delegated MCP calls| Services[Downstream MCP services]

    Services -->|optional hub callbacks| HubMCP[Reserved hub MCP tools]
    HubMCP --> HubStore[HubResultStore]
    HubStore --> Memory[In-memory store]
    HubStore --> Cache[Optional external cache]
~~~

## 3. Main runtime building blocks

### 3.1 MCP entrypoint

`app/main_mcp.py` is the runtime bootstrap. It:

1. loads typed configuration from `GofrAgentConfig`
2. loads the services manifest from YAML or environment
3. creates the `ServiceRegistry`
4. starts the configured hub store backend
5. builds the `GofrAgent`
6. creates the FastMCP server and wraps it in the production ASGI app
7. applies inbound transport security and auth middleware
8. exposes public `GET /ping`, public `GET /health`, and authenticated MCP tools on `/mcp`

The runtime shape is intentionally simple: one ASGI process hosting both the MCP
tool plane and the compact health endpoints.

### 3.2 FastMCP server

`app/mcp_server/mcp_server.py` defines the public MCP tools. The current control
plane includes:

- `ping`
- `health_check`
- `list_services`
- `ask`
- `reset_session`
- `register_service`
- `refresh_services`
- `get_pending_user_input`
- `respond_to_user_input`
- `cancel_user_input`

It also exposes reserved results-hub tools for downstream services:

- `_store_result`
- `_get_result`
- `_describe_result`

Those reserved hub tools are not model-visible. They are protocol plumbing for
service-to-service handoff through `gofr-agent`.

### 3.3 Reasoning engine

`app/agent/agent.py` wraps a shared pydantic-ai `Agent` instance. The shared
instance is rebuilt whenever the service registry changes, but each `ask` run is
isolated by its own prompt, message history, usage limits, request id, and event
collector.

The reasoning engine is responsible for:

- building the final prompt from the current question, session summary, and caller content
- enforcing max-step and timeout limits
- emitting live reasoning events
- running the model/tool loop
- compacting long session history into summaries
- optionally pausing for deterministic missing-field prompts in interactive mode
- optionally emitting verification gaps and provenance when the feature flags are enabled

### 3.4 Service registry and pools

`app/services/registry.py` owns the downstream service catalogue.

For each configured service it keeps:

- the resolved `ServiceConfig`
- a `SessionPool`
- the discovered MCP tool descriptors
- current health status
- optional results-hub capability metadata

`app/services/pool.py` holds a small pool of long-lived MCP client sessions per
service. These pooled sessions are used for bootstrap connectivity and tool
discovery.

User-driven downstream tool execution is intentionally different from discovery:

- discovery uses the service's configured service token through the pool
- runtime tool execution opens a fresh one-shot downstream session using the caller's bearer token

That split avoids mixing one requester's privileges into another requester's tool
calls.

### 3.5 Session store

`app/sessions/store.py` keeps conversation state in memory. Each session stores:

- recent raw message history
- a compacted summary of older history
- last-active timestamps for TTL expiry
- one pending human-input prompt when interactive mode pauses a run

This state is process-local today. A restart loses it. Multi-replica deployment
therefore needs sticky routing or a shared backing store before session portability
is real.

### 3.6 Results hub

The built-in results hub is a bounded handoff layer for large JSON payloads.
Instead of forcing the model to carry large tool outputs inline, producer services
can store payloads in the hub and return a descriptor. Consumer services can later
resolve that descriptor through reserved hub tools.

The hub store has two backend shapes behind the same interface:

- `memory`: process-local in-memory store
- `external_cache`: external cache adapter, currently designed for Valkey/Redis-compatible deployment

The hub is optional and disabled by default.

## 4. Startup flow

The startup path is where `gofr-agent` turns a static manifest into a live tool
catalogue.

~~~mermaid
sequenceDiagram
    autonumber
    participant Boot as app.main_mcp
    participant Registry as ServiceRegistry
    participant Pool as SessionPool
    participant Service as Downstream MCP service
    participant HubStore as HubResultStore
    participant Agent as GofrAgent
    participant MCP as FastMCP server

    Boot->>Registry: load manifest
    loop each enabled service
        Registry->>Pool: start pool
        Pool->>Service: initialize pooled MCP sessions
        Registry->>Service: list tools
        Service-->>Registry: tool descriptors
        opt hub enabled and service exposes _register_results_hub
            Registry->>Service: _register_results_hub(...)
            Service-->>Registry: capabilities or registration error
        end
    end
    Boot->>HubStore: start configured backend
    Boot->>Agent: build model-visible tools from registry
    Boot->>MCP: create server + auth guards + transport security
~~~

Important startup behavior:

- service registration is best-effort; a failing service degrades the registry instead of preventing the process from starting
- hub registration errors are recorded per service and surfaced through health/list APIs
- reserved hub tools are filtered out of the model-facing tool catalogue
- the agent tool set is generated from the current discovered registry state, not from hard-coded Python tool definitions

## 5. Normal `ask` request flow

The core runtime path is an authenticated `ask` call.

### 5.1 Request handling steps

1. The caller sends `ask(...)` to `/mcp` over Streamable HTTP.
2. FastMCP routes the tool call.
3. `gofr-agent` validates the bearer token and checks `GoFRAgentAsk`.
4. Request fields are bounded and normalized.
5. The session is created or reopened in `SessionStore`.
6. If the session already has pending user input, the request is rejected until the caller answers, cancels, or the prompt expires.
7. An event collector is attached so live reasoning notifications and final `steps` come from the same source.
8. `GofrAgent.run(...)` builds the final prompt, reads prior message history, and starts a bounded pydantic-ai run.
9. The model alternates between thought nodes and tool-call nodes.
10. Each downstream tool call is authorized and executed through a generated wrapper.
11. New messages are appended to session history, with summary compaction when limits are exceeded.
12. The final MCP response returns `answer`, `steps`, `status`, `tokens_used`, and optional `verification_gap`, `clarification_request`, or `provenance`.

### 5.2 Downstream tool execution

Generated tool wrappers in `app/agent/tool_factory.py` do more than simple
forwarding. On each tool call they:

1. validate tool arguments against the downstream JSON schema
2. optionally enrich missing required arguments from recent structured tool outputs
3. enforce requester intent constraints when that feature is enabled
4. derive the downstream activity name for the specific service/tool pair
5. require that activity against the caller's token
6. open a fresh downstream MCP session using the caller's bearer token
7. optionally inject hub context headers for services that support descriptor workflows
8. call the downstream MCP tool
9. truncate oversized returned text for model safety
10. remember structured results as artifacts for later tool calls and provenance

This is the key execution distinction in the system:

- pooled sessions are for service bootstrap and connectivity
- one-shot delegated sessions are for user-scoped tool execution

### 5.3 Live reasoning stream

Reasoning events are emitted as MCP `notifications/message` entries with logger
`gofr-agent.reasoning`.

Current event families include:

- run lifecycle: `run_started`, `run_completed`, `run_failed`
- step lifecycle: `step_started`, `step_completed`
- model text: `text_delta`
- tool execution: `tool_call`, `tool_retry`, `tool_result`
- session compaction: `summary_update`
- interactive flow: `user_input_requested`, `run_paused`, `user_input_received`, `run_resumed`, `user_input_cancelled`

The final `steps` array is derived from that same event stream, not built by a
separate code path.

## 6. Interactive pause/resume flow

Interactive mode is a small extension of the normal `ask` flow.

When verification-gap handling is enabled and deterministic missing fields are
detected before the LLM run starts, the agent can return:

- `status: "waiting_for_user"`
- `is_complete: false`
- `user_input_request` with `prompt_id`, `run_id`, prompt text, and expiry

The pending prompt is stored in the session. The caller then uses:

- `get_pending_user_input` to recover state after reconnect
- `respond_to_user_input` to resume the run
- `cancel_user_input` to abandon the paused prompt

This keeps human latency out of the original open request while preserving the
session-scoped context.

## 7. Results hub architecture

The results hub exists to keep large intermediate payloads out of model context.

### 7.1 Why the hub exists

Without the hub, the model would have to carry large JSON results from one tool
call to a later tool call in plain text. That is expensive, brittle, and unsafe.

With the hub enabled:

1. a producer service stores a large JSON payload through `_store_result`
2. the hub returns a compact descriptor
3. the producer returns that descriptor or a bounded summary to the model
4. a consumer service later receives the descriptor as an argument
5. the consumer resolves the authoritative payload through `_get_result` or `_describe_result`

The model sees the descriptor metadata, not the full stored payload.

### 7.2 Startup capability registration vs runtime use

There are two separate hub phases.

Startup phase:

- the registry checks whether a service advertises `_register_results_hub`
- if so, `gofr-agent` sends hub protocol details and records whether the service can publish or consume results

Runtime phase:

- tool wrappers mint per-call hub context for the current session
- downstream services use that session-bound context when calling the hub tools back on `gofr-agent`

Startup registration is only capability discovery. It is not the runtime auth
mechanism for hub access.

### 7.3 Hub security and isolation

Hub access is session-scoped and service-scoped.

At runtime the tool wrapper can inject:

- the hub URL
- a signed short-lived callback token

That callback token binds together:

- downstream service identity
- allowed hub operations
- allowed result types
- a session-derived namespace
- request and run correlation when available

The hub then resolves access scope from trusted server-side context instead of
trusting arbitrary downstream-supplied session identifiers.

### 7.4 Hub store backends

The hub store boundary is intentionally interface-based.

Current backend options:

- `memory`: simplest path, process-local, good for tests and lightweight single-process runs
- `external_cache`: production-like cache shape, still bounded by TTL and explicit capacity limits, designed so only `gofr-agent` talks to the cache directly

In both cases, the hub enforces:

- protocol version checks
- JSON-serializable payloads only
- maximum payload size
- maximum per-session result count
- TTL expiry
- expected result-type and schema checks on reads

## 8. Security and trust boundaries

The architecture has four important trust boundaries.

### 8.1 Client to gofr-agent

Inbound `/mcp` traffic is protected by:

- FastMCP transport security checks for Host and Origin
- optional CORS configuration for browser cases
- bearer-token extraction and per-activity authorization on MCP tools

Public `/ping` and `/health` stay intentionally low-detail. Rich diagnostics live
behind authenticated MCP tools.

### 8.2 gofr-agent to downstream MCP services

`gofr-agent` discovers services from a trusted manifest or guarded dynamic
registration path. At execution time it forwards the caller's token to downstream
tools instead of reusing a pooled bootstrap token.

This means downstream services can enforce subject-aware authorization rather than
implicitly trusting `gofr-agent` as a superuser.

### 8.3 Downstream services to the results hub

Hub callbacks are authorized by dedicated callback tokens and constrained by
operation and result-type scopes. Reserved hub tools are hidden from the model but
still fully auth-checked on the server.

### 8.4 Untrusted content to the model

The model is treated as a component that needs protection. Tool results, caller
content, descriptors, and session summaries are treated as data, not as higher-
priority instructions. Optional prompt-hardening flags strengthen this boundary.

## 9. State, failure, and degradation model

The current architecture favors bounded, explicit failure over hidden fallback.

Key properties:

- sessions are in-memory and TTL-based
- pending human-input state is in-memory and TTL-based
- service startup failures degrade the registry instead of aborting the whole process
- pool reconnects are background retries with backoff
- hub external-cache failures return structured hub errors instead of silently switching to in-memory mode after startup
- health output distinguishes healthy, degraded, and failed downstream states

This keeps failure handling observable and keeps the control plane available even
when some downstream services are unavailable.

## 10. Deployment topologies

### 10.1 Baseline single-process topology

This is the default mental model today.

~~~text
client/proxy
  -> gofr-agent /mcp
     -> downstream MCP services
     -> in-memory SessionStore
     -> in-memory hub store when enabled
~~~

Good for tests, fixture chat, and simple development runs.

### 10.2 External-cache hub topology

This is the preferred production-like dev shape for descriptor workflows.

~~~text
client/proxy
  -> gofr-agent /mcp
     -> downstream MCP services
     -> in-memory SessionStore
     -> external HubResultStore adapter
        -> Valkey/Redis-compatible cache on the same Docker network
~~~

In this shape, downstream services still talk only to `gofr-agent` hub tools.
They do not talk to the cache directly.

## 11. Current architectural constraints

The most important current constraints are:

1. sessions and pending prompts are process-local
2. the results hub is bounded handoff storage, not durable system-of-record storage
3. multi-replica deployment needs sticky routing or shared state before session portability is real
4. interactive pause/resume is Phase 1A only for deterministic pre-LLM missing-field prompts
5. prompt-hardening and provenance features exist but several remain default-off for compatibility

## 12. Where to look next

For deeper detail by surface:

- `docs/current_state.md` for what is implemented now
- `docs/master_specification.md` for the top-level product and protocol model
- `docs/security_model.md` for auth, transport, hub, and model-safety boundaries
- `docs/reasoning_stream_sequence_diagram.md` for step-by-step runtime sequences
- `docs/results_hub_cache_design.md` for the external-cache hub topology and rationale
- `docs/human_in_the_loop_strategy.md` for pause/resume behavior and constraints

Taken together, the current architecture is a bounded async orchestrator: a
single MCP endpoint that authenticates callers, dynamically learns downstream
tools, executes those tools under caller identity, and optionally uses a session-
scoped results hub so large service outputs move between MCP services without
passing through the model as raw payloads.