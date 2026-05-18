# Security Model

This document describes the security model implemented by `gofr-agent` today.
It focuses on the code paths that are actually enforced in the current server,
not on future production architecture.

## Goals

The current design tries to protect four things:

- access to the `gofr-agent` MCP control plane
- access to downstream MCP tools
- large or privileged result payloads exchanged through the optional results hub
- the model itself from instruction injection through tool output or caller-supplied content

The main controls are bearer-token authorization, FastMCP transport security,
per-tool activity checks, capability-scoped hub access, and prompt-hardening
guards.

## Trust Boundaries

There are four important trust boundaries in the system:

1. Client to `gofr-agent`

   Clients talk to `gofr-agent` over Streamable HTTP on `/mcp`. This boundary is
   protected by Host and Origin validation, optional CORS policy, and bearer-token
   authorization on MCP tools.

2. `gofr-agent` to downstream MCP services

   `gofr-agent` registers downstream services from a manifest or runtime
   registration, discovers tools, and then calls those tools on behalf of the
   requester.

3. Services to the optional results hub

   When the built-in hub is enabled, services can publish and consume result
   payloads through reserved hub tools using service callback tokens.

4. Untrusted content to the model

   Tool descriptions, tool output, descriptors, caller-pasted content, and
   session summaries are treated as data, not as instructions.

## Inbound HTTP and MCP Surface

`gofr-agent` exposes three public HTTP entry points:

- `GET /ping`
- `GET /health`
- `POST` and `GET` on `/mcp`

### Public health endpoints

`/ping` and `/health` are intentionally unauthenticated. They are designed as
sanitized operational endpoints, not as rich diagnostics.

- `/ping` returns only basic reachability data.
- `/health` returns compact readiness status and downstream service counts.
- Detailed config and runtime state are available only through the authenticated
  `health_check` MCP tool.

This means the public HTTP surface is small and intentionally low detail.

### MCP transport security

Before the ASGI app is created, `gofr-agent` applies FastMCP transport security
settings from `GofrAgentConfig`.

These settings enforce:

- Host allow-list validation via `GOFR_AGENT_MCP_ALLOWED_HOSTS`
- Origin allow-list validation via `GOFR_AGENT_MCP_ALLOWED_ORIGINS`
- DNS rebinding protection via `GOFR_AGENT_MCP_DNS_REBINDING_PROTECTION_ENABLED`

Optional browser CORS policy is configured separately through
`GOFR_AGENT_CORS_ORIGINS`. CORS is not the primary authorization mechanism; it
only controls browser access behavior. Host and Origin validation still happen
at the MCP transport layer.

For browser and UI flows, the expected MCP request headers are:

- `Authorization`
- `Content-Type`
- `Accept`
- `Mcp-Session-Id`
- `Mcp-Protocol-Version`

## Authentication and Authorization

### Fail-closed default

The auth factory defaults to `FailClosedAuthService`, which authorizes nothing.
Unless the process is started with `GOFR_AGENT_AUTH_MODE=dev` or another auth
service is injected in tests, all bearer tokens are denied.

This is an important part of the current security model: production auth is not
silently permissive. The default behavior is deny-all.

### Dev auth mode

When `GOFR_AGENT_AUTH_MODE=dev`, the server uses a fixed token map:

- `dev-admin-token`: all built-in agent activities plus `MCPServer*`
- `dev-read-token`: read-oriented agent activities plus `GoFRAgentAsk`, but no downstream `MCPServer*`
- `dev-fixtures-hub-token`: hub callback activities only

This split is deliberate. It allows local testing of the common failure mode
where a token can call `ask` but cannot invoke downstream tools.

### Per-activity checks

Every MCP tool in `app/mcp_server/mcp_server.py` calls `_guard(...)` before doing
any real work. `_guard(...)`:

- extracts the bearer token from the request context
- validates its shape
- checks that the token grants the required activity
- fails the request with an MCP error if auth is missing or denied

Examples:

- `ask` requires `GoFRAgentAsk`
- `list_services` requires `GoFRAgentListServices`
- `reset_session` requires `GoFRAgentResetSession`
- `model_override` requires both `GoFRAgentAsk` and `GoFRAgentModelOverride`

Downstream tool calls are protected separately. Each model-visible downstream
tool maps to a derived activity name of the form:

`MCPServer<ServiceName>Tool<ToolName>`

The wildcard `MCPServer*` grants all downstream tool activities.

## Downstream Service Security Model

### Service registration and secrets

Downstream services are loaded from `services.yml`, another manifest file, or
environment variables.

Each service can define:

- `token` or `token_env`
- `hub_callback_token` or `hub_callback_token_env`

Resolved secret values are intentionally omitted from `ServiceConfig.safe_dump()`,
which is what `list_services` uses. This prevents `list_services` from exposing
service tokens or hub callback tokens.

### Dynamic registration

Dynamic registration is disabled by default.

If `GOFR_AGENT_DYNAMIC_REGISTRATION_ENABLED=true`, runtime registration is still
constrained by `GOFR_AGENT_ALLOWED_SERVICE_HOSTS`. The service URL hostname must
match that allow-list or registration is rejected.

This is the primary server-side control preventing a caller from registering an
arbitrary outbound destination.

### Discovery and tool execution use different credentials

`gofr-agent` intentionally separates service bootstrap credentials from
user-driven tool execution credentials.

1. Persistent pool sessions

   The `SessionPool` uses the service's configured `token` when opening the
   background pooled sessions used for discovery and ongoing connectivity.

2. User-driven downstream tool calls

   When the model calls a downstream tool, `gofr-agent` does not reuse the pooled
   service token. Instead it:

   - checks that the caller token grants the specific downstream activity
   - opens a fresh one-shot downstream session with the caller's bearer token
   - closes that session after the tool call completes

This avoids mixing one caller's privileges with another's and makes downstream
authorization subject-aware. It also means downstream services must accept the
same user token model that `gofr-agent` is using for delegated tool execution.

## Results Hub Security Model

The results hub is optional and disabled by default.

When enabled, `gofr-agent` exposes reserved protocol tools:

- `_store_result`
- `_get_result`
- `_describe_result`

These tools are not exposed in the model-visible tool list.

Hub authorization is different from normal caller authorization:

- callers must still pass the relevant hub activity (`GoFRAgentHubStore` or
  `GoFRAgentHubFetch`)
- the bearer token is then resolved to a service principal using the registered
  service's `hub_callback_token`
- token comparison uses `secrets.compare_digest`
- the resolved principal is checked for publish/consume permissions and allowed
  result types

The hub therefore enforces both identity and capability:

- which service the token belongs to
- whether that service may publish results
- whether that service may consume results
- which result types it is allowed to touch

When hub mode is enabled, `hub_url` must be configured and must not point to
`localhost` or a loopback address.

## Model-Safety and Prompt-Safety Controls

The security model is not only about network auth. The model itself is treated
as a component that needs protection from untrusted inputs.

### Authority hierarchy

The hardened system prompt defines an explicit authority order:

1. system prompt
2. authenticated requester instructions
3. registered service tool outputs for facts in their domains
4. caller-asserted facts, pasted content, descriptors, and session summaries as data only

This is meant to stop tool output or pasted content from overriding server-side
behavior.

### Untrusted tool and caller content

The prompt and tool factory both treat downstream outputs as untrusted data.

- tool results are wrapped in explicit sentinel blocks
- tool and service metadata can be sanitized before being added to the prompt
- descriptor arguments must be passed through verbatim instead of expanded into
  raw payloads
- missing factual inputs should be gathered from tools or the requester, not guessed

### Optional hardening flags

Several feature flags strengthen model behavior when enabled:

- `GOFR_AGENT_PROMPT_HARDENING_V2_ENABLED`
- `GOFR_AGENT_INTENT_CONSTRAINTS_ENABLED`
- `GOFR_AGENT_GROUNDING_ENFORCEMENT_ENABLED`
- `GOFR_AGENT_VERIFICATION_GAP_RESPONSE_ENABLED`
- `GOFR_AGENT_PROVENANCE_IN_RESPONSE_ENABLED`

These do not replace auth or transport security. They reduce prompt injection,
constraint drift, and unverified factual output.

## Data Minimization and Secret Exposure

The current implementation uses several data-minimization patterns:

- service manifests can source secrets from env vars instead of inline YAML
- `list_services` excludes resolved service tokens and hub callback tokens
- authenticated `health_check` returns only boolean secret-presence signals such
  as `openrouter_api_key_configured`, not secret values
- unauthenticated `/health` is even more compact and omits detailed config

This is not a claim that secrets can never be exposed by operator error or by
future code changes. It is a description of the current intended surfaces.

## Operational Guidance

For local UI testing, the documented helper scripts run the server in `dev`
auth mode and use `dev-admin-token` as the simplest bearer token that grants
both agent activities and downstream `MCPServer*` activities.

For non-local deployments, the intended posture is:

- do not rely on dev auth tokens
- keep dynamic registration disabled unless there is a clear operational need
- restrict `GOFR_AGENT_MCP_ALLOWED_HOSTS` and `GOFR_AGENT_MCP_ALLOWED_ORIGINS`
  to known callers
- store downstream service tokens and hub callback tokens outside committed
  manifests when possible
- enable prompt-hardening and grounding features when factual correctness and
  prompt-injection resistance matter more than permissive behavior

## Current Limitations

The current security model has a few important limitations:

1. The default non-dev auth implementation is deny-all, not a full production
   identity integration. A real deployment needs an injected or integrated auth
   backend.

2. Service URLs are validated only as `http://` or `https://` URLs. The stronger
   outbound network policy for service reachability is operational and
   configuration-based, not fully encoded in URL validation.

3. The results hub and dynamic-registration controls depend on correct service
   configuration and allow-lists. They are not a substitute for network-layer
   isolation.

4. Model-safety features are feature-flagged. If those flags are disabled, the
   system still enforces auth and transport controls, but has weaker resistance
   to prompt injection and factual drift.

In short: `gofr-agent` is designed to fail closed on auth, restrict inbound MCP
transport, authorize each MCP action explicitly, use subject-aware bearer tokens
for delegated downstream tool calls, and treat model-facing content as untrusted
data. Production security still depends on correct deployment, real auth
integration, and tight allow-list configuration.