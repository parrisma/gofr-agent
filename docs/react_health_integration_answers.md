# React Health Integration Answers for LLM Builders

Status date: 2026-05-17.

Audience: an LLM coding assistant writing a React/TypeScript UI for
`gofr-agent`.

Use this document as a narrow health-readiness brief. The broader UI contract is
in [react_integration_guide.md](react_integration_guide.md). This document
answers the health questions the UI should make visible without inventing extra
backend behavior.

## Rule of thumb

Use HTTP health routes for unauthenticated process and readiness checks. Use MCP
tools for tokened access and diagnostic details.

| Surface | Auth | Call | Use |
|---------|------|------|-----|
| HTTP ping | none | `GET ${agentHttpBaseUrl(mcpUrl)}/ping` | Is the process reachable? |
| HTTP health | none | `GET ${agentHttpBaseUrl(mcpUrl)}/health` | Is the server broadly ready? |
| MCP `ping` | bearer token | `client.callTool({ name: "ping", arguments: {} })` | Can this token call MCP tools? |
| MCP `health_check` | bearer token | `client.callTool({ name: "health_check", arguments: {} })` | What model, limits, flags, and downstream service states are active? |
| MCP `list_services` | bearer token | `client.callTool({ name: "list_services", arguments: {} })` | What tools and service capabilities should the UI show? |

Derive HTTP health URLs from the configured MCP URL. Do not ask the user for a
second origin unless the deployment actually uses a separate proxy.

```ts
export function agentHttpBaseUrl(mcpUrl: string): string {
  const url = new URL(mcpUrl);
  url.pathname = url.pathname.replace(/\/mcp\/?$/, "");
  url.search = "";
  url.hash = "";
  return url.toString().replace(/\/$/, "");
}
```

## Question 1: Is the MCP server process reachable?

Answer this with HTTP `GET /ping` before creating the MCP client.

Expected response:

```ts
type PingResponse = {
  status: "ok";
  service: "gofr-agent";
  timestamp: string;
  version: string;
};
```

UI behavior:

- If `/ping` succeeds, show that the process is reachable and display the
  version in connection metadata.
- If `/ping` fails with a network error, show an unavailable server state.
- If the browser blocks the request with CORS, show a deployment configuration
  problem, not an auth problem.
- Do not treat `/ping` success as proof that the bearer token works. It is
  intentionally unauthenticated.

If HTTP `/ping` succeeds but MCP traffic returns `421 Invalid Host header`, the
process is reachable and the blocker is the backend MCP Host-header allowlist,
not the React health probe.

## Question 2: Is the reasoning agent configured and ready?

Answer this in two stages:

1. Use HTTP `GET /health` for token-free readiness.
2. Use MCP `health_check` after MCP connection for detailed readiness.

Expected HTTP response:

```ts
type HttpHealthResponse = {
  status: "healthy" | "degraded" | "unhealthy";
  service: "gofr-agent";
  timestamp: string;
  version: string;
  message: string;
  downstream: {
    total: number;
    healthy: number;
    degraded: number;
    failed: number;
  };
};
```

HTTP status behavior:

- `200` means the server reports `healthy` or `degraded`.
- `503` means the server reports `unhealthy`.
- A degraded downstream service should not block the chat surface by itself.

UI behavior:

- `healthy`: show normal connected/readiness state.
- `degraded`: show a warning banner or status pill, keep chat enabled, and let
  the user inspect details after MCP diagnostics load.
- `unhealthy`: show a blocking readiness state for normal chat requests.
- If HTTP health succeeds but MCP connection fails, separate the messages:
  server reachable, MCP/auth unavailable.

## Question 3: Which model is selected by default, and which overrides are allowed?

Answer this with MCP `health_check`, not HTTP `/health`.

Relevant response fields:

```ts
type HealthModels = {
  selected: string;
  allowed_overrides: string[];
  openrouter_api_key_configured: boolean;
};
```

UI behavior:

- Display `config.models.selected` as the active default model.
- Display `config.models.allowed_overrides` only when the product exposes a
  model selector. If the list is empty, hide the selector or show a disabled
  default-only state.
- Use `openrouter_api_key_configured` only as an operator diagnostic. Never ask
  the browser user to enter the backend API key unless the product has a
  separate secure credential-management flow.
- When an `ask` call returns its final payload, prefer the returned `model` for
  that specific turn because it reflects what actually ran.

## Question 4: Which downstream MCP services are connected, degraded, failed, or hub-capable?

Use MCP `health_check` for status counts and safe health details. Use MCP
`list_services` for model-visible tool names and descriptions.

Relevant health fields:

```ts
type HealthDownstreamServices = {
  total: number;
  healthy: number;
  degraded: number;
  failed: number;
  items: Array<{
    name: string;
    status: "healthy" | "degraded" | "failed";
    tool_count: number;
    supports_results_hub: boolean;
    can_publish_results: boolean;
    can_consume_results: boolean;
    result_types: string[];
    error?: string;
    registration_error?: string;
  }>;
};
```

UI behavior:

- Show summary counts from `downstream_services.total`, `healthy`, `degraded`,
  and `failed`.
- Render each service with status, tool count, and hub capability indicators.
- Show `error` and `registration_error` in a details disclosure. They are
  bounded and sanitized, but still operational detail.
- Treat service failures as degraded capability unless the overall status is
  `unhealthy`.
- Do not call hidden hub tools from the browser. The UI may display hub
  capability booleans, but descriptor resolution is internal server behavior.
- For service tool names and descriptions, call `list_services`; do not use
  `health_check` as the full capabilities source.

## Question 5: Which runtime limits and feature flags are active?

Answer this with MCP `health_check`.

Relevant response fields:

```ts
type HealthRuntimeConfig = {
  limits: Record<string, number>;
  sessions: Record<string, number>;
  features: Record<string, boolean>;
  hub: Record<string, boolean | number>;
};
```

UI behavior:

- Use `limits.max_steps_hard_cap` to cap the `maxSteps` input.
- Use `limits.max_question_chars` and `limits.max_context_chars` for client-side
  validation hints, but still let the server enforce the final rule.
- Use session values for settings/help text, not as a browser-side source of
  truth for server history.
- Use feature flags to show or hide optional UI affordances such as dynamic
  service registration, prompt hardening metadata, and results hub diagnostics.
- Do not assume missing flags are enabled. Unknown or absent fields should be
  treated as disabled by default.

## Question 6: Why does MCP traffic return `421 Invalid Host header`?

Answer: the incoming HTTP `Host` header used for `/mcp` is not in FastMCP's
inbound transport-security `allowed_hosts` list. This is a backend deployment
configuration blocker. It is separate from bearer-token auth, CORS, and
downstream service registration policy.

What the React UI can do:

- Use the operator-provided public MCP URL or same-origin proxy URL. Do not use
  an internal Docker service name from browser code unless the browser can
  actually resolve and reach it.
- Surface `421 Invalid Host header` as: server reachable, MCP host not
  allowlisted by the backend.
- Include the configured MCP URL host in non-secret diagnostics so an operator
  can see which hostname needs to be allowlisted.
- Retry only after settings change; repeated retries with the same URL/token
  will not fix a Host-header rejection.

What the React UI must not do:

- Do not try to set or spoof the `Host` header from browser code. Browsers do
  not allow that header to be set by JavaScript.
- Do not treat this as an expired-token problem. Auth has not reached the tool
  guard when FastMCP rejects the Host header.
- Do not confuse this with `GOFR_AGENT_ALLOWED_SERVICE_HOSTS`; that setting is
  for outbound runtime service registration, not inbound browser/proxy traffic
  to `gofr-agent`.

Backend/operator answer:

- Configure FastMCP transport security so `allowed_hosts` includes every host
  and port form that can appear on inbound MCP requests. Typical entries are
  the public browser hostname, reverse-proxy hostname, Docker service hostname,
  and development hostnames such as `127.0.0.1:*` when local testing requires
  them.
- If a reverse proxy is in front of `gofr-agent`, decide whether the proxy
  preserves the public `Host` header or rewrites it to the upstream service
  name. Allowlist the value the backend actually receives.
- Keep DNS-rebinding protection enabled. Fix the allowlist; do not disable the
  protection just to make MCP traffic pass.

## Recommended startup sequence

1. Derive `httpBaseUrl` from `mcpUrl`.
2. Call HTTP `/ping`.
3. Call HTTP `/health` and populate the initial connection banner.
4. Create the MCP client with the bearer token.
5. Call MCP `ping` to confirm tokened tool access.
6. Call MCP `health_check` for diagnostics.
7. Call MCP `list_services` for the capabilities panel.

Keep the error states distinct:

- Network/CORS failure on HTTP probes: server or deployment reachability issue.
- HTTP `/health` returns `unhealthy`: server process answered but the agent is
  not ready.
- MCP returns `421 Invalid Host header`: backend inbound Host-header allowlist
  does not include the URL/proxy host used for MCP traffic.
- MCP connect or MCP `ping` authorization failure: token or MCP auth issue.
- MCP `health_check` returns `degraded`: show details, keep core chat available.

## What not to expose

The React UI must not expect or display these values because the backend health
surface intentionally omits them:

- Bearer tokens.
- API keys.
- Vault secrets.
- Callback tokens.
- Downstream service URLs from health payloads.
- Raw user/session contents.
- Raw large tool results or results-hub payloads.

If the UI needs full service tool descriptions, call `list_services`. If it
needs full answer provenance, use the `ask` response and reasoning events. Keep
health checks focused on readiness and diagnostics.