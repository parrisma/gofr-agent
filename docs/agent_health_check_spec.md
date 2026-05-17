# gofr-agent Health Check Specification

Status: DRAFT - requires user approval before implementation.
Date: 2026-05-17.

## Purpose

Add gofr-iq-style ping and health-check capability to gofr-agent so operators,
LLM clients, and UI clients can quickly answer:

- Is the MCP server process reachable?
- Is the reasoning agent configured and ready?
- Which model is selected by default, and which overrides are allowed?
- Which downstream MCP services are connected, degraded, failed, or hub-capable?
- Which key runtime limits and feature flags are active?

The goal is diagnostic visibility without exposing bearer tokens, API keys,
callback tokens, Vault secrets, or raw user/session contents.

## Source pattern from gofr-iq

The relevant gofr-iq implementation has two complementary surfaces:

- `app/web_server/web_server.py` exposes HTTP `GET /health` and `GET /ping`.
  These return compact process reachability metadata: `status`, `service`,
  `timestamp`, `version`, and a note pointing REST users to MCPO.
- `app/main_mcp.py` appends a lightweight HTTP `GET /health` route to the MCP
  Starlette app because MCP Streamable HTTP itself is session-based and not a
  good load-balancer health target.
- `app/tools/health_tools.py` registers an MCP `health_check` tool. It returns
  an overall `healthy | degraded | unhealthy` status plus per-dependency detail
  for Neo4j, ChromaDB, and LLM configuration. The LLM section exposes model
  names and whether an API key is configured, but not the key itself.
- Tool descriptions throughout gofr-iq refer users and LLMs to `health_check`
  when downstream tools fail unexpectedly.

gofr-agent should reuse the shape and intent, but adapt the dependency list to
its own runtime: model configuration, auth availability, session limits, the
service registry, downstream service pools, and results-hub configuration.

## Current gofr-agent state

gofr-agent currently exposes an authenticated MCP `ping` tool in
`app/mcp_server/mcp_server.py`. It returns:

```json
{
  "status": "ok",
  "timestamp": "...",
  "version": "..."
}
```

There is no HTTP `/ping` or `/health` route on the uvicorn app, and there is no
MCP `health_check` tool with detailed diagnostics.

`list_services` already exposes safe downstream service metadata and hub
capability fields. The health-check implementation should build on that
existing safe surface rather than duplicating secret-bearing service config.

## Proposed external surfaces

### 1. HTTP `GET /ping`

Purpose: unauthenticated process reachability probe for load balancers,
orchestrators, and simple curl checks.

Response shape:

```json
{
  "status": "ok",
  "service": "gofr-agent",
  "timestamp": "2026-05-17T12:00:00+00:00",
  "version": "0.1.0"
}
```

This endpoint must not perform downstream network calls and must not expose
configuration details beyond service identity and version.

### 2. HTTP `GET /health`

Purpose: unauthenticated operational health endpoint for process and dependency
readiness.

Response shape:

```json
{
  "status": "healthy",
  "service": "gofr-agent",
  "timestamp": "2026-05-17T12:00:00+00:00",
  "version": "0.1.0",
  "message": "All registered services are healthy",
  "downstream": {
    "total": 2,
    "healthy": 2,
    "degraded": 0,
    "failed": 0
  }
}
```

The HTTP health endpoint should stay safe for infrastructure systems. It should
not include model names, allowed model overrides, service URLs, auth details, or
secret/config internals. Detailed diagnostics belong in the authenticated MCP
`health_check` tool.

HTTP status code behavior:

- `200` when overall status is `healthy` or `degraded`.
- `503` when overall status is `unhealthy` because the process cannot build the
  health payload or a critical internal dependency is unusable.

Downstream service failures should normally produce `degraded`, not `unhealthy`,
because gofr-agent can still accept requests, report gaps, and serve non-tool
operations while a downstream service is unavailable.

### 3. MCP `ping`

Purpose: authenticated lightweight MCP reachability check.

Keep the existing MCP tool and extend it conservatively to include `service` for
consistency with HTTP ping and gofr-common helpers:

```json
{
  "status": "ok",
  "service": "gofr-agent",
  "timestamp": "2026-05-17T12:00:00+00:00",
  "version": "0.1.0"
}
```

The tool should continue to require `GoFRAgentPing`.

### 4. MCP `health_check`

Purpose: authenticated diagnostic tool for users, LLM clients, CLI clients, and
future React UI integration.

New activity: `GoFRAgentHealthCheck`.

Recommended response shape:

```json
{
  "status": "healthy",
  "message": "All registered services are healthy",
  "service": "gofr-agent",
  "timestamp": "2026-05-17T12:00:00+00:00",
  "version": "0.1.0",
  "config": {
    "models": {
      "selected": "openai:gpt-4o-mini",
      "allowed_overrides": [],
      "openrouter_api_key_configured": false
    },
    "limits": {
      "agent_timeout_seconds": 120,
      "max_steps": 10,
      "max_steps_hard_cap": 50,
      "max_question_chars": 8000,
      "max_context_chars": 16000,
      "max_event_payload_chars": 4000,
      "max_response_steps": 200,
      "tool_result_max_chars": 4000,
      "tool_retry_attempts": 2
    },
    "sessions": {
      "session_ttl_minutes": 60,
      "max_sessions": 1000,
      "max_messages_per_session": 100,
      "sweep_interval_seconds": 60
    },
    "features": {
      "hub_enabled": false,
      "dynamic_registration_enabled": false,
      "prompt_hardening_v2_enabled": false,
      "caller_content_structured_enabled": false,
      "intent_constraints_enabled": false,
      "grounding_enforcement_enabled": false,
      "verification_gap_response_enabled": false,
      "provenance_in_response_enabled": false,
      "interactive_default": false,
      "allow_unauthenticated_resume": false
    },
    "hub": {
      "enabled": false,
      "hub_url_configured": false,
      "protocol_version": 1,
      "default_ttl_seconds": 3600,
      "max_payload_bytes": 524288,
      "max_results": 256
    }
  },
  "downstream_services": {
    "total": 1,
    "healthy": 1,
    "degraded": 0,
    "failed": 0,
    "items": [
      {
        "name": "instruments",
        "status": "healthy",
        "tool_count": 3,
        "supports_results_hub": true,
        "can_publish_results": true,
        "can_consume_results": false,
        "result_types": ["ohlcv_bars"]
      }
    ]
  }
}
```

## Security and privacy constraints

The health-check payload must never include:

- bearer tokens
- OpenRouter API keys or any other provider keys
- Vault root tokens, AppRole secrets, JWT signing secrets, or callback tokens
- inline service `token` or `hub_callback_token` values
- raw session messages, user prompts, answers, pending prompt values, or tool
  payloads
- full exception tracebacks

Allowed diagnostic fields:

- boolean `*_configured` flags for secrets
- selected model id and allow-listed model override ids
- bounded config limits and feature flags
- service names, safe statuses, tool counts, hub capability flags, and bounded
  error messages already considered safe by `list_services`

## Status rules

Overall MCP `health_check` status should be computed as follows:

- `healthy`: core server is running and every registered downstream service is
  `healthy`. Zero downstream services can still be healthy, with a message that
  no downstream services are registered.
- `degraded`: one or more downstream services are `degraded` or `failed`, or hub
  registration errors exist, while the gofr-agent process itself can still
  answer requests.
- `unhealthy`: the server cannot construct the health payload, the agent has not
  been built, or a critical injected dependency is missing in a way that prevents
  normal MCP operation.

The first implementation should avoid active probing of downstream services on
each health request. It should report registry/pool state already maintained by
`ServiceRegistry`, matching the lightweight style of `list_services`. Active
probe/reconnect behavior can be added later if needed.

## Documentation requirements

After implementation, update:

- `README.md` configuration and MCP tools sections.
- `docs/current_state.md` implemented runtime surfaces.
- `docs/master_specification.md` MCP tool contract section.
- `docs/react_integration_guide.md` health-check UI guidance.
