# gofr-agent React Integration Guide for LLM Builders

Status date: 2026-05-17.

Audience: an LLM coding assistant working in a React/TypeScript codebase that
needs to design, build, and test a UI for `gofr-agent`.

Use this as the implementation brief. It describes the current backend surface,
the UI that should be built first, the TypeScript contracts to model, and the
tests that should prove the interface works.

For repository-wide runtime status, see [current_state.md](current_state.md).
For a narrower question-by-question health brief, see
[react_health_integration_answers.md](react_health_integration_answers.md).

## 1. LLM operating rules

When using this document to build a React interface:

1. Build the actual chat workbench as the first screen. Do not build a landing
   page, marketing hero, or explanatory splash screen.
2. Use the official MCP TypeScript SDK. Do not hand-roll MCP JSON-RPC.
3. Treat the server as authoritative. Do not invent client-only pause/resume,
   descriptor resolution, service discovery, or hidden tool behavior.
4. Keep production secrets out of the browser bundle. A dev token can be used
   for local development only.
5. Do not hard-code `localhost` for service-to-service traffic. In Docker/dev
   environments use routable hostnames such as `http://gofr-agent:8090/mcp`.
   For browser deployments use the operator-provided public origin.
6. Design for an operations-style application: dense, calm, readable, and built
   for repeated use. The core user workflow is ask, watch progress, inspect
   sources/tools, and continue the session.

## 2. Current backend surface

`gofr-agent` is an MCP Streamable HTTP server. It wraps a `pydantic-ai`
reasoning agent and lets that agent call registered downstream MCP services.

Current facts a UI-building LLM must preserve:

| Item | Current value or behavior |
|------|---------------------------|
| Transport | MCP Streamable HTTP |
| Endpoint path | `/mcp` |
| HTTP health paths | `/ping` and `/health` on the same host/port as `/mcp` |
| Default Docker/dev URL | `http://gofr-agent:8090/mcp` |
| MCP port | `8090` |
| mcpo proxy port | `8091`, not the preferred React path |
| Reserved future web UI port | `8092`, no web UI is implemented in this repo |
| Auth | Bearer token in `Authorization` on every MCP request |
| HTTP health auth | No bearer token required for `GET /ping` or `GET /health` |
| Dev admin token | `dev-admin-token` |
| Dev read token | `dev-read-token`, includes `ping`, `health_check`, `list_services`, and `ask` |
| Session model | Server-side in-memory history keyed by caller-provided `session_id` |
| Session TTL default | 60 idle minutes |
| Default max steps | 10 |
| Hard max steps | 50 |
| Agent timeout default | 120 seconds |
| Final response | Returned by the MCP `ask` tool after the run finishes |
| Live progress | MCP `notifications/message` with logger `gofr-agent.reasoning` |
| Results hub | Optional, process-local descriptor handoff between services |

Browser clients usually cannot call an internal Docker service name directly.
The deployed React app needs an externally reachable MCP origin or a same-origin
backend proxy. If the React app is served from a different origin, the operator
must configure CORS on the Starlette/Uvicorn deployment to allow the browser
origin and the `Authorization` header.

MCP traffic is also subject to FastMCP inbound Host and Origin protection. The
backend reads these settings from:

- `GOFR_AGENT_MCP_ALLOWED_HOSTS`
- `GOFR_AGENT_MCP_ALLOWED_ORIGINS`
- `GOFR_AGENT_MCP_DNS_REBINDING_PROTECTION_ENABLED`
- `GOFR_AGENT_CORS_ORIGINS`

If `/mcp` returns `421 Invalid Host header`, the backend allowlist does not
include the Host value received on that request. If it returns
`403 Invalid Origin header`, the backend allowlist does not include the browser
Origin. These are not fixed by changing the bearer token or by React setting a
`Host` header; browser JavaScript cannot set that header. The backend/operator
must allowlist the public/proxy/Docker Host and Origin values used for MCP
traffic. Do not confuse this with `GOFR_AGENT_ALLOWED_SERVICE_HOSTS`, which
controls outbound runtime service registration.

For the local console topology, the backend should explicitly allow the console
browser origins and the Host value the agent actually receives through the proxy:

```text
GOFR_AGENT_MCP_ALLOWED_HOSTS=gofr-agent-dev,gofr-agent-dev:8090,gofr-agent:8090,127.0.0.1:*,localhost:*,[::1]:*
GOFR_AGENT_MCP_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://gofr-console-dev:3000
GOFR_AGENT_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://gofr-console-dev:3000
```

After a backend version with this contract is deployed, the console proxy can
remove its Origin-stripping workaround. The browser should continue to call the
same-origin console proxy; MCP chat and tool calls remain bearer-authenticated.
Unauthenticated `GET /ping` and `GET /health` stay compact and safe. Detailed
runtime diagnostics, including model, limits, feature flags, and downstream
service details, are available through authenticated MCP `health_check`.
Downstream degraded state remains HTTP 200 with JSON `status: degraded`, and
invalid bearer tokens still fail closed during MCP tool execution.

## 3. React configuration inputs

The React app should make these values configurable through environment, a
settings panel, or the host application's auth layer:

| UI setting | Purpose | Suggested default for local dev |
|------------|---------|---------------------------------|
| `mcpUrl` | Full MCP Streamable HTTP URL | `http://gofr-agent:8090/mcp` |
| `token` | Bearer token | `dev-admin-token` only in local dev |
| `sessionId` | Chat thread identifier | `crypto.randomUUID()` |
| `maxSteps` | Per-question tool-call cap | 20 in UI, never above server hard cap |
| `outputFormat` | Optional final answer shape | unset, `text`, or `json` |
| `toolsOnly` | Require factual answers from tools | false by default |
| `allowedServices` | Optional service allow-list | unset |
| `forbiddenServices` | Services the user disallows | unset |
| `forbiddenTools` | Tools the user disallows | unset |

Production token guidance:

- Do not bake long-lived bearer tokens into the static bundle.
- Prefer a same-origin backend that injects or exchanges tokens.
- If the browser must hold a token, make it short-lived and scoped to the user.
- The UI should treat auth failures as recoverable configuration errors.

## 4. MCP client contract

Use these packages in the React project:

```bash
npm install @modelcontextprotocol/sdk
```

Connect with `StreamableHTTPClientTransport`:

```ts
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

export async function createGofrClient(opts: { url: string; token: string }) {
  const transport = new StreamableHTTPClientTransport(new URL(opts.url), {
    requestInit: {
      headers: { Authorization: `Bearer ${opts.token}` },
    },
  });

  const client = new Client(
    { name: "gofr-agent-react-ui", version: "0.1.0" },
    { capabilities: {} },
  );

  await client.connect(transport);
  await client.setLoggingLevel("info");
  return client;
}
```

The MCP SDK returns tool results as `CallToolResult` objects. For `gofr-agent`
tools, the first content item is text containing JSON. Parse it before updating
React state.

```ts
export function parseTextJson<T>(result: { content?: unknown[] }): T {
  const first = result.content?.[0] as { type?: string; text?: string } | undefined;
  if (!first || typeof first.text !== "string") {
    throw new Error("Expected gofr-agent tool response to contain JSON text");
  }
  return JSON.parse(first.text) as T;
}
```

HTTP health routes live next to `/mcp`, not under it. Derive the HTTP base URL
from the configured MCP URL instead of making users configure the same origin
twice.

```ts
export function agentHttpBaseUrl(mcpUrl: string): string {
  const url = new URL(mcpUrl);
  url.pathname = url.pathname.replace(/\/mcp\/?$/, "");
  url.search = "";
  url.hash = "";
  return url.toString().replace(/\/$/, "");
}
```

## 5. MCP tools visible to the React UI

All public tools require the bearer token.

| Tool | UI use |
|------|--------|
| `ping` | Startup health check |
| `health_check` | Diagnostics/settings panel and degraded-service detail |
| `list_services` | Capabilities panel and feature availability |
| `ask` | Main chat request |
| `respond_to_user_input` | Submit an answer to a Phase 1A pending prompt |
| `get_pending_user_input` | Recover a pending prompt after reconnect or refresh |
| `cancel_user_input` | Clear a pending prompt the user abandoned |
| `reset_session` | Clear current server-side conversation history |
| `register_service` | Admin-only runtime service registration |
| `refresh_services` | Admin-only refresh of discovered service metadata |

The Phase 1A user-input tools are protected by dedicated activities but may be
listed by FastMCP/mcpo. Treat authorization as the security boundary, not tool
visibility.

Hidden/internal hub tools also exist on the MCP server: `_store_result`,
`_get_result`, and `_describe_result`. Downstream services use them for results
hub callbacks. The React UI should not call them.

Downstream services may expose a reserved `_register_results_hub` tool. The
service registry uses it during discovery. It is filtered out of model-visible
and UI-facing tool lists.

## 6. Health surfaces the UI can call

Use the smallest health surface that answers the UI question. The HTTP routes
are unauthenticated process/readiness probes. The MCP tools prove tokened MCP
access and expose diagnostics.

| Surface | Auth | URL or call | UI use |
|---------|------|-------------|--------|
| HTTP ping | none | `GET ${agentHttpBaseUrl(mcpUrl)}/ping` | Pre-auth process reachability and deployment smoke check |
| HTTP health | none | `GET ${agentHttpBaseUrl(mcpUrl)}/health` | Compact readiness banner before MCP connection or when token is unknown |
| MCP `ping` | bearer token with `GoFRAgentPing` | `client.callTool({ name: "ping", arguments: {} })` | Confirm the configured token can call MCP tools |
| MCP `health_check` | bearer token with `GoFRAgentHealthCheck` | `client.callTool({ name: "health_check", arguments: {} })` | Diagnostics/settings panel, degraded-service details, selected model, feature flags |

HTTP status behavior for `GET /health`:

- `200` means the server reports `healthy` or `degraded`.
- `503` means the server reports `unhealthy`.
- Downstream service failures normally produce `degraded`, not `unhealthy`, so
  the UI should keep the chat surface available while showing degraded-service
  warnings.

Recommended startup flow:

1. Call HTTP `GET /ping` to distinguish unreachable server from bad token.
2. Call HTTP `GET /health` to load compact readiness and downstream counts.
3. Connect the MCP client with the bearer token.
4. Call MCP `ping` to verify tokened MCP access.
5. Call MCP `health_check` for settings/diagnostics, then `list_services` for
   model-visible tool names and descriptions.

If browser CORS blocks the HTTP probes, treat it as a deployment configuration
issue. The HTTP routes do not need auth, but the deployment still must allow the
browser origin to call them.

If HTTP `/ping` succeeds but MCP calls fail with `421 Invalid Host header`, show
an MCP host-allowlist configuration error. The process is reachable; the backend
Host-header allowlist for `/mcp` needs the URL or proxy host that the browser is
using.

## 7. Public health payloads

### HTTP `GET /ping`

Request: no bearer token required.

Response: same shape as MCP `ping`.

```ts
type PingResponse = {
  status: "ok";
  service: "gofr-agent";
  timestamp: string;
  version: string;
};
```

UI behavior: use this before MCP connection when the user edits the MCP URL or
opens settings. A successful response says only that the process can answer; it
does not validate the bearer token.

### HTTP `GET /health`

Request: no bearer token required.

Response:

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

UI behavior: use this for a compact connection banner and operations summary.
It intentionally omits selected model, allowed model overrides, service URLs,
tool names, tokens, API keys, and raw errors. Show `degraded` as a warning state
with chat still enabled; show `unhealthy` as a blocking server-readiness state.

### MCP `ping`

Arguments: none.

Response:

```ts
type PingResponse = {
  status: "ok";
  service: "gofr-agent";
  timestamp: string;
  version: string;
};
```

UI behavior: call on app start and when the user changes URL/token settings.
Show connected, unauthorized, unavailable, and misconfigured states distinctly.
This is the right check when the UI needs to know whether the supplied bearer
token can make MCP tool calls. For token-free reachability, call HTTP
`GET /ping`.

### MCP `health_check`

Arguments: none.

Response summary:

```ts
type HealthCheckResponse = {
  status: "healthy" | "degraded" | "unhealthy";
  message: string;
  service: "gofr-agent";
  timestamp: string;
  version: string;
  config: {
    models: {
      selected: string;
      allowed_overrides: string[];
      openrouter_api_key_configured: boolean;
    };
    limits: Record<string, number>;
    sessions: Record<string, number>;
    features: Record<string, boolean>;
    hub: Record<string, boolean | number>;
  };
  downstream_services: {
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
};
```

UI behavior: use this for diagnostics/settings surfaces and when a request or
tool call fails. The payload is sanitized for display: it uses boolean
`*_configured` flags for secrets and does not return service URLs, bearer
tokens, callback tokens, API keys, or raw session/tool payloads. For a token-free
orchestrator probe, call HTTP `GET /health`; that endpoint returns only status,
message, version, and downstream counts.

Status handling:

- `healthy`: normal connected state.
- `degraded`: show warnings for downstream services or hub registration errors,
  but keep chat available.
- `unhealthy`: show a blocking readiness message; MCP may be reachable, but the
  agent is not ready for normal operation.

Do not use `health_check` instead of `list_services` for the full capabilities
panel. `health_check` gives counts and safe service health items; `list_services`
adds model-visible tool names and descriptions.

## 8. Public tool payloads

### `list_services`

Arguments: none.

Response:

```ts
type ServiceTool = {
  name: string;
  description: string;
};

type ServiceStatus = {
  name: string;
  url?: string;
  description?: string;
  enabled?: boolean;
  status: string;
  tools: ServiceTool[];
  supports_results_hub: boolean;
  can_publish_results: boolean;
  can_consume_results: boolean;
  result_types: string[];
  error?: string;
  registration_error?: string;
};
```

The returned hub capability fields are safe to display. Tokens and callback
credentials are never returned by `list_services`.

UI behavior:

- Show a compact service list with status, tool count, and hub capability.
- Expand a service to show model-visible tool names and descriptions.
- Surface `error` and `registration_error` without treating the whole app as
  failed; the registry can run in degraded mode.
- Do not expose hidden `_store_result`, `_get_result`, `_describe_result`, or
  `_register_results_hub` tools as user-invokable actions.

### `ask`

Arguments:

```ts
type AskRequest = {
  question: string;
  session_id?: string;
  interactive?: boolean;
  context?: string;
  instructions?: string;
  asserted_facts?: string[];
  pasted_content?: string[];
  forbidden_services?: string[];
  forbidden_tools?: string[];
  allowed_services?: string[];
  tools_only?: boolean;
  output_format?: "json" | "text";
  no_commentary?: boolean;
  max_steps?: number;
  model_override?: string;
};
```

Validation enforced by the server:

- `question` is required, trimmed, and cannot be empty.
- `question` defaults to an 8000 character limit.
- Combined context/caller content defaults to a 16000 character limit.
- `output_format` must be `json` or `text` when provided.
- `max_steps` must be at least 1 and no greater than the server hard cap.
- `model_override` must be non-empty, authorized, and present in
  `GOFR_AGENT_ALLOWED_MODELS`.

Response:

```ts
type AskResponse = {
  session_id: string;
  request_id: string;
  status: "completed" | "waiting_for_user" | "cancelled";
  is_complete: boolean;
  run_id: string;
  answer: string;
  user_input_request: HumanInputRequest | null;
  steps: ReasoningEvent[];
  model: string;
  tokens_used: number;
  verification_gap: VerificationGap | null;
  clarification_request: ClarificationRequest | null;
  provenance: ProvenanceRecord[];
};

type HumanInputRequest = {
  prompt_id: string;
  run_id: string;
  session_id: string;
  prompt: string;
  input_schema?: Record<string, unknown> | null;
  choices?: string[] | null;
  created_at: string;
  expires_at: string;
  missing_fields: string[];
};
```

UI behavior:

- Append the user message immediately.
- Start a run state keyed by local turn id and later bind it to `request_id`.
- Render live reasoning notifications while the `ask` promise is in flight.
- Check `status` when `ask` resolves. If it is `waiting_for_user`, render
  `user_input_request.prompt` and collect a bounded answer instead of treating
  the empty `answer` as final text.
- Append the final assistant answer when `status` is `completed`.
- Render `verification_gap` and `clarification_request` as successful run
  outcomes, not transport failures.
- Preserve and reuse the returned `session_id` for follow-up turns.
- Show `model`, `tokens_used`, and `request_id` in compact turn metadata.

Phase 1A resume tools:

```ts
type RespondToUserInputRequest = {
  session_id: string;
  prompt_id: string;
  value: unknown;
};

type GetPendingUserInputResponse =
  | { status: "waiting_for_user"; session_id: string; run_id: string; user_input_request: HumanInputRequest }
  | { status: "not_found" | "expired"; session_id: string; user_input_request: null };

type CancelUserInputResponse = {
  status: "cancelled" | "not_found" | "expired";
  session_id: string;
  prompt_id: string;
};
```

Client behavior:

- Call `respond_to_user_input` with the returned `session_id`, `prompt_id`,
  and a bounded JSON value. The response has the same envelope as `ask`.
- Call `get_pending_user_input` after reconnect or page refresh if the local
  turn is waiting.
- Call `cancel_user_input` when the user abandons a waiting prompt.
- Treat the user value as data in the UI too; do not turn it into system or
  developer instructions.

### `reset_session`

Arguments:

```ts
type ResetSessionRequest = { session_id: string };
type ResetSessionResponse = { status: "ok"; session_id: string };
```

UI behavior: provide a clear conversation action. After success, clear local
turns and reasoning state for that thread, or create a fresh `session_id`.

### `register_service` and `refresh_services`

These are admin-only. Most React chat interfaces should hide them unless the
product explicitly includes service administration.

`register_service` is disabled unless
`GOFR_AGENT_DYNAMIC_REGISTRATION_ENABLED=true`, and the target host must match
`GOFR_AGENT_ALLOWED_SERVICE_HOSTS`.

## 9. Reasoning notifications

During `ask`, the server emits MCP logging notifications:

| Field | Value |
|-------|-------|
| MCP method | `notifications/message` |
| Logger | `gofr-agent.reasoning` |
| Payload location | `notification.params.data` |
| Correlation | `request_id`, also returned by final `ask` response |

Register the handler immediately after connecting:

```ts
client.setNotificationHandler("notifications/message", notification => {
  if (notification.params?.logger !== "gofr-agent.reasoning") return;
  const payload = notification.params?.data;
  if (!payload || typeof payload !== "object") return;
  onReasoningEvent(payload as ReasoningEvent);
});
```

Shared event fields:

```ts
type ReasoningEventBase = {
  request_id: string;
  session_id: string;
  run_id?: string | null;
  event_id: string;
  sequence: number;
  kind: string;
  timestamp: string;
  truncated: boolean;
};
```

Current event kinds:

| Kind | UI meaning |
|------|------------|
| `run_started` | The run began; may include `question` |
| `step_started` | A thought, tool call, summary, or final-answer step started |
| `text_delta` | Incremental model text |
| `tool_call` | A downstream tool was requested |
| `tool_retry` | A transient downstream failure is being retried |
| `tool_result` | A downstream tool completed |
| `summary_update` | Older session history was compacted |
| `step_completed` | A logical step finished |
| `run_completed` | The run finished successfully |
| `run_failed` | The run failed before completion |
| `user_input_requested` | A Phase 1A prompt is ready to show |
| `run_paused` | The logical run is waiting for user input |
| `user_input_received` | A resume request supplied an answer; raw value is not included |
| `run_resumed` | The logical run resumed after user input |
| `user_input_cancelled` | The pending prompt was cancelled |

Important event-specific fields:

```ts
type ToolCallEvent = ReasoningEventBase & {
  kind: "tool_call";
  service: string;
  tool: string;
  arguments: Record<string, unknown>;
  attempt: number;
};

type ToolResultEvent = ReasoningEventBase & {
  kind: "tool_result";
  service: string;
  tool: string;
  ok: boolean;
  summary: unknown;
  attempt: number;
  latency_ms?: number | null;
  args_hash?: string | null;
  artifact_id?: string | null;
  as_of?: string | null;
};

type RunCompletedEvent = ReasoningEventBase & {
  kind: "run_completed";
  model?: string | null;
  answer_preview?: string | null;
  tokens_used?: number | null;
};

type RunFailedEvent = ReasoningEventBase & {
  kind: "run_failed";
  error: string;
  fatal: boolean;
};
```

Reasoning event UI rules:

- Sort by `sequence`, not arrival time.
- Use `event_id` for stable React keys.
- Show `text_delta` only in an optional live draft area; final `steps` excludes
  `text_delta` events.
- Treat `truncated: true` as a signal to show a compact warning.
- Do not render raw large data as primary UI. Tool summaries are bounded by the
  server and may be intentionally abbreviated.
- Tool arguments can contain user data. Put them behind a details disclosure in
  normal views.

## 10. Human-in-the-loop status

Phase 1A pause/resume is implemented for deterministic missing-field prompts
that are detected before the LLM run starts. LLM-initiated prompts from inside
the pydantic-ai run remain Phase 1B.

Config includes:

- `GOFR_AGENT_INTERACTIVE_DEFAULT`
- `GOFR_AGENT_PENDING_PROMPT_TTL_SECONDS`
- `GOFR_AGENT_ALLOW_UNAUTHENTICATED_RESUME`

The public MCP `ask` tool accepts `interactive?: boolean`. When interactive is
enabled and `allow_unauthenticated_resume` is false, the server rejects the call
before agent execution because `AuthService` does not yet expose a stable
subject binding. Developer/test deployments can enable
`GOFR_AGENT_ALLOW_UNAUTHENTICATED_RESUME=true`.

What the UI should do now:

- Send `interactive: true` only when the product wants the Phase 1A waiting
  flow and the deployment enables resume.
- Render `clarification_request` from non-interactive final responses as a
  normal assistant ask-back.
- Render `user_input_request` from `status: "waiting_for_user"` as a pending
  prompt tied to `run_id` and `prompt_id`.
- Submit answers with `respond_to_user_input`, recover pending prompts with
  `get_pending_user_input`, and abandon them with `cancel_user_input`.
- Keep the older manual follow-up flow available for deployments where
  interactive resume is disabled.

## 11. Results hub and descriptors

When `GOFR_AGENT_HUB_ENABLED=true`, `gofr-agent` can act as a process-local
results hub for descriptor handoff between downstream MCP services.

UI-facing rules:

- Descriptors such as `{"kind":"gofr.result_ref", ...}` are internal
  references, not user-facing answers.
- Do not try to resolve result descriptors from the browser.
- Do not call `_get_result` or `_describe_result` from the UI.
- Do not expect descriptors to contain the large payload they refer to.
- Reasoning notifications intentionally avoid streaming raw payloads such as
  OHLCV arrays.
- A debug-only view may show descriptor metadata, `artifact_id`, `args_hash`,
  and `as_of` values when present.

Known hub limitation: the store is in-memory and process-local. Multi-replica
deployments need sticky routing or a shared store before descriptors are
portable across replicas.

## 12. Prompt hardening response models

These response fields are present in the `ask` payload and are enabled or
populated depending on server flags.

```ts
type VerificationGapReason =
  | "no_service_registered"
  | "tool_error"
  | "empty_result"
  | "schema_mismatch"
  | "contradiction"
  | "policy_denied"
  | "constraint_blocked"
  | "max_steps_reached";

type VerificationGapAttempt = {
  service?: string | null;
  tool?: string | null;
  args_summary?: Record<string, unknown> | string | null;
  outcome: string;
};

type VerificationGap = {
  request_id: string;
  requested_fact: string;
  attempted: VerificationGapAttempt[];
  reason: VerificationGapReason;
  options: string[];
};

type ClarificationRequest = {
  request_id: string;
  question: string;
  missing_fields: string[];
  reason: string;
  prompt: string;
};

type ProvenanceRecord = {
  request_id: string;
  service: string;
  tool: string;
  args_hash: string;
  artifact_id?: string | null;
  attempt: number;
  ok: boolean;
  latency_ms?: number | null;
  truncated: boolean;
  as_of?: string | null;
};
```

UI behavior:

- `verification_gap`: show a clear non-error state explaining that the agent
  could not verify the requested fact. Include attempted services/tools in an
  expandable section.
- `clarification_request`: render the `prompt` as the assistant response and
  make `missing_fields` visible in metadata or a structured prompt card.
- `provenance`: show in a source/details panel, not inline in the main answer.
- `as_of`: when present, display freshness near the relevant source/tool.

## 13. Recommended React information architecture

Build a compact workbench with these areas:

| Area | Purpose |
|------|---------|
| Chat transcript | User and assistant turns, final answers, clarification prompts |
| Composer | Question input, send button, optional output/constraint controls |
| Run trace | Live reasoning events for the active turn |
| Capabilities | Services, tool counts, hub capability, degraded-service warnings |
| Settings | MCP URL, auth status, max steps, session controls |
| Metadata | Request id, model, tokens, duration, provenance summary |

Expected controls:

- Icon or icon+text buttons for send, stop/cancel UI state, reset, refresh, and
  settings.
- Numeric input or stepper for `maxSteps`.
- Segmented control for output format: default, text, JSON.
- Toggles for `toolsOnly` and `noCommentary`.
- Multi-select or checkboxes for allowed/forbidden services when exposed.
- Collapsible sections for service tools, reasoning trace, provenance, and raw
  debug JSON.

Do not put explanatory marketing copy in the main viewport. The first screen
should let the user ask a question immediately.

## 14. State model the React LLM should implement

Use explicit state rather than deriving everything from text.

```ts
type ConnectionState =
  | { status: "idle" }
  | { status: "checking" }
  | {
      status: "connected";
      version: string;
      health?: "healthy" | "degraded" | "unhealthy";
      message?: string;
      downstream?: HttpHealthResponse["downstream"];
    }
  | { status: "unauthorized"; message: string }
  | { status: "unavailable"; message: string };

type TurnStatus =
  | "queued"
  | "running"
  | "completed"
  | "waiting_for_user"
  | "verification_gap"
  | "clarification_requested"
  | "failed";

type ChatTurn = {
  id: string;
  role: "user" | "assistant";
  text: string;
  status?: TurnStatus;
  requestId?: string;
  model?: string;
  tokensUsed?: number;
  events?: ReasoningEvent[];
  pendingUserInput?: HumanInputRequest | null;
  verificationGap?: VerificationGap | null;
  clarificationRequest?: ClarificationRequest | null;
  provenance?: ProvenanceRecord[];
  error?: string;
};
```

Reducer guidance:

- Keep a `pendingTurnId` for the in-flight user/assistant pair.
- Before final `request_id` is known, attach notifications to a temporary
  pending bucket; once `ask` resolves, bind by `request_id`.
- If a notification includes a `request_id` that already exists, append it to
  that turn's event list.
- If `run_failed` arrives, mark the active turn failed but still wait for the
  `ask` promise to settle so transport errors and model errors are not mixed.
- Keep local turns separate from server session history. The server stores
  model-side history by `session_id`; the browser stores display state.

## 15. Reference hook

This is a starting point, not a full app.

```ts
import { useCallback, useRef, useState } from "react";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

type UseGofrAgentOptions = {
  url: string;
  token: string;
  defaultMaxSteps?: number;
};

export function useGofrAgent(opts: UseGofrAgentOptions) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [services, setServices] = useState<ServiceStatus[]>([]);
  const [health, setHealth] = useState<HttpHealthResponse | HealthCheckResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const sessionId = useRef(crypto.randomUUID());
  const clientRef = useRef<Client | null>(null);
  const pendingAssistantTurnId = useRef<string | null>(null);

  const ensureClient = useCallback(async () => {
    if (clientRef.current) return clientRef.current;

    const transport = new StreamableHTTPClientTransport(new URL(opts.url), {
      requestInit: { headers: { Authorization: `Bearer ${opts.token}` } },
    });
    const client = new Client(
      { name: "gofr-agent-react-ui", version: "0.1.0" },
      { capabilities: {} },
    );

    await client.connect(transport);
    await client.setLoggingLevel("info");
    client.setNotificationHandler("notifications/message", notification => {
      if (notification.params?.logger !== "gofr-agent.reasoning") return;
      const payload = notification.params?.data;
      if (!payload || typeof payload !== "object") return;
      const event = payload as ReasoningEvent;
      setTurns(prev =>
        prev.map(turn => {
          const matchesRequest = turn.requestId && turn.requestId === event.request_id;
          const matchesPending = !turn.requestId && turn.id === pendingAssistantTurnId.current;
          if (!matchesRequest && !matchesPending) return turn;
          return { ...turn, events: [...(turn.events ?? []), event] };
        }),
      );
    });

    clientRef.current = client;
    return client;
  }, [opts.token, opts.url]);

  const refreshServices = useCallback(async () => {
    const client = await ensureClient();
    const result = await client.callTool({ name: "list_services", arguments: {} });
    setServices(parseTextJson<ServiceStatus[]>(result));
  }, [ensureClient]);

  const checkHttpHealth = useCallback(async () => {
    const response = await fetch(`${agentHttpBaseUrl(opts.url)}/health`);
    const data = (await response.json()) as HttpHealthResponse;
    setHealth(data);
    return data;
  }, [opts.url]);

  const refreshDiagnostics = useCallback(async () => {
    const client = await ensureClient();
    const result = await client.callTool({ name: "health_check", arguments: {} });
    const data = parseTextJson<HealthCheckResponse>(result);
    setHealth(data);
    return data;
  }, [ensureClient]);

  const ask = useCallback(
    async (question: string, overrides: Partial<AskRequest> = {}) => {
      const trimmed = question.trim();
      if (!trimmed) return;

      const userTurn: ChatTurn = {
        id: crypto.randomUUID(),
        role: "user",
        text: trimmed,
      };
      const assistantTurn: ChatTurn = {
        id: crypto.randomUUID(),
        role: "assistant",
        text: "",
        status: "running",
        events: [],
      };
      pendingAssistantTurnId.current = assistantTurn.id;
      setTurns(prev => [...prev, userTurn, assistantTurn]);
      setBusy(true);

      try {
        const client = await ensureClient();
        const result = await client.callTool({
          name: "ask",
          arguments: {
            question: trimmed,
            session_id: sessionId.current,
            max_steps: opts.defaultMaxSteps ?? 20,
            ...overrides,
          },
        });
        const data = parseTextJson<AskResponse>(result);
        sessionId.current = data.session_id;

        setTurns(prev =>
          prev.map(turn => {
            if (turn.id !== assistantTurn.id) return turn;
            const status = data.status === "waiting_for_user"
              ? "waiting_for_user"
              : data.verification_gap
                ? "verification_gap"
                : data.clarification_request
                  ? "clarification_requested"
                  : "completed";
            return {
              ...turn,
              text:
                data.answer ||
                data.user_input_request?.prompt ||
                data.clarification_request?.prompt ||
                "",
              status,
              requestId: data.request_id,
              model: data.model,
              tokensUsed: data.tokens_used,
              events: data.steps.length > 0 ? data.steps : turn.events,
              pendingUserInput: data.user_input_request,
              verificationGap: data.verification_gap,
              clarificationRequest: data.clarification_request,
              provenance: data.provenance,
            };
          }),
        );
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        setTurns(prev =>
          prev.map(turn =>
            turn.id === assistantTurn.id
              ? { ...turn, status: "failed", error: message, text: message }
              : turn,
          ),
        );
      } finally {
        pendingAssistantTurnId.current = null;
        setBusy(false);
      }
    },
    [ensureClient, opts.defaultMaxSteps],
  );

  const reset = useCallback(async () => {
    const client = await ensureClient();
    await client.callTool({
      name: "reset_session",
      arguments: { session_id: sessionId.current },
    });
    sessionId.current = crypto.randomUUID();
    pendingAssistantTurnId.current = null;
    setTurns([]);
  }, [ensureClient]);

  return { turns, services, health, busy, ask, reset, refreshServices, checkHttpHealth, refreshDiagnostics };
}
```

## 16. Error handling

Handle these cases explicitly:

| Case | Likely cause | UI response |
|------|--------------|-------------|
| Missing/invalid token | Bad settings or expired token | Show auth error and settings action |
| CORS failure | Browser origin not allowed | Show deployment/configuration message |
| `421 Invalid Host header` on `/mcp` | MCP Host header not allowlisted by backend FastMCP transport security | Show backend host-allowlist configuration message |
| Network failure | Server unreachable | Show reconnect action |
| HTTP health degraded | Downstream service or hub registration issue | Show warning but keep chat available |
| HTTP health unhealthy | Core agent readiness failure | Show blocking readiness state |
| `max_steps` rejected | Value exceeds hard cap | Clamp and explain |
| Tool-call limit reached | Run exhausted configured steps | Suggest retry with higher max steps |
| Verification gap | Could not verify requested fact | Show gap details, not an error toast |
| Clarification request | Missing material input | Show ask-back and let user send another turn |
| `waiting_for_user` | Interactive Phase 1A prompt | Show pending prompt, then call `respond_to_user_input` |
| Pending prompt expired | Prompt TTL elapsed or process restarted | Clear local pending state and let the user retry |
| `run_failed` event | Runtime/model/tool failure | Mark active turn failed and preserve trace |

## 17. Build checklist for the React-side LLM

Implement in this order:

1. Create or locate the React/TypeScript app shell.
2. Add `@modelcontextprotocol/sdk`.
3. Add a typed `gofrAgentClient` module with `createGofrClient` and
  `parseTextJson`.
4. Add TypeScript types for `AskRequest`, `AskResponse`, `HumanInputRequest`,
  `ReasoningEvent`, `PingResponse`, `HttpHealthResponse`,
  `HealthCheckResponse`, `ServiceStatus`, `VerificationGap`,
  `ClarificationRequest`, and `ProvenanceRecord`.
5. Add a reducer or hook for connection, turns, events, services, and settings.
6. Build the chat transcript and composer.
7. Add HTTP health probes, MCP `ping`, MCP `health_check`, and service list
  loading.
8. Add live reasoning trace rendering from notifications.
9. Add reset session.
10. Add advanced constraints only after the basic chat path works.
11. Add provenance, verification gap, clarification, and Phase 1A pending
    prompt rendering.
12. Add `respond_to_user_input`, `get_pending_user_input`, and
    `cancel_user_input` client helpers.
13. Add tests before broad styling work.

Do not implement these until backend support exists or the product explicitly
requests admin features:

- LLM-initiated mid-run user-input submission beyond deterministic Phase 1A
  prompts.
- Browser-side descriptor resolution.
- Dynamic service registration in the normal user chat surface.
- Model override controls for ordinary users.

## 18. Test plan for the React-side LLM

Unit tests:

- `parseTextJson` parses valid MCP text JSON.
- `parseTextJson` rejects missing text content.
- `agentHttpBaseUrl` maps `/mcp` URLs to the sibling HTTP route base.
- Reasoning event reducer appends by pending turn id before `request_id` is
  known.
- Reasoning event reducer appends by `request_id` after final response.
- Event sorting uses `sequence`.
- `verification_gap` maps to `verification_gap` turn status.
- `clarification_request` maps to `clarification_requested` turn status.
- Service list hides or ignores reserved hub tools if they ever appear.

Component tests:

- Initial settings render with URL/token/max steps.
- Successful HTTP `/ping` shows server reachable before token validation.
- HTTP `/health` with `degraded` shows a warning, not a blocking error.
- Successful MCP `ping` moves tokened connection state to connected.
- Unauthorized MCP `ping` shows an auth state.
- MCP `health_check` renders selected model, feature flags, and degraded
  service details without exposing tokens or service URLs.
- `list_services` renders degraded services without crashing.
- Sending a question appends user and assistant turns.
- A `tool_call` notification appears in the trace before final answer.
- Reset calls `reset_session` and clears local turns.

Integration tests with a mocked MCP client:

- `ask` success with live events and final answer.
- `ask` response containing `verification_gap`.
- `ask` response containing `clarification_request`.
- Transport/network error.
- `run_failed` notification followed by a rejected `ask` promise.

End-to-end tests when a dev server and gofr-agent are available:

1. Configure MCP URL and token.
2. Verify HTTP ping and health are reachable.
3. Verify MCP ping and `health_check` work with the configured token.
4. Verify services load.
5. Ask `What tools are available?`.
6. Confirm an assistant answer appears.
7. Confirm at least one reasoning event or completed step is visible.
8. Reset the session and confirm the transcript clears.

If changing this Python backend while building the UI, validate backend changes
with this repository's wrapper, not raw pytest:

```bash
./scripts/run_tests.sh
```

For docs-only changes in this repository, at minimum run:

```bash
git diff --check
```

## 19. Useful backend references

- MCP server tools: [../app/mcp_server/mcp_server.py](../app/mcp_server/mcp_server.py)
- Runtime config: [../app/config.py](../app/config.py)
- Reasoning events: [../app/agent/events.py](../app/agent/events.py)
- Response contracts: [../app/agent/contracts.py](../app/agent/contracts.py)
- Current state: [current_state.md](current_state.md)
- README: [../README.md](../README.md)
