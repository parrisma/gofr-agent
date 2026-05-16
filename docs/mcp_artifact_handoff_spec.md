# MCP Results Hub Handoff Spec

Status: DRAFT v3
Review basis: `docs/peer_review.md`

## Purpose

Large structured tool results should not be passed through model text and then
recopied into later tool calls. gofr-agent already has connections to every
registered downstream MCP service, so gofr-agent acts as the results hub.

The hub protocol lets producer services publish large results to gofr-agent and
return compact descriptors. Consumer services receive descriptors and fetch the
payload from gofr-agent by GUID. The model sees descriptors, not payloads.

This spec uses the term "result" throughout. Earlier "artifact" wording is
retired.

## Terminology

| Term | Meaning |
|------|---------|
| Results hub | gofr-agent, acting as the central temporary result store |
| Producer service | Downstream MCP service that creates a large result |
| Consumer service | Downstream MCP service that needs a previously produced result |
| Result descriptor | Small JSON object containing protocol fields, metadata, and `result_guid` |
| Result payload | Large structured JSON value stored in the hub |
| Hub-capable service | Downstream MCP service that supports hub registration |
| Callback credential | Service-level bearer token used by a downstream service when calling hub tools |

## Goals

1. Support large structured cross-tool inputs without forcing the model to carry
   the payload.
2. Keep gofr-agent as the only coordination point; downstream services do not
   talk to each other.
3. Let downstream services discover the hub during service registration.
4. Keep result descriptors explicit, typed, bounded, and machine-checkable.
5. Treat the hub's stored metadata as the source of truth.
6. Hide hub-protocol tools from the model.
7. Preserve compatibility for services that do not support descriptors.

## Non-goals

1. No service mesh between downstream services.
2. No descriptor signing in the first implementation.
3. No permanent result storage in the first implementation.
4. No binary/blob streaming in the first implementation.
5. No migration of every tool at once; start with the OHLCV analytics workflow.
6. No multi-replica gofr-agent in the first implementation.
7. No per-end-user ownership rule for result fetches in the first implementation.

## Trust Model

The trust model is intentionally simple and relies on platform boundaries rather
than new descriptor cryptography.

Foundations:

1. gofr-agent is the only component that initiates downstream service
   registration. Downstream URLs and outbound tokens come from gofr-agent's own
   config.
2. MCP transport uses bearer-token auth on every service call and every callback
   into the hub.
3. Result GUIDs are cryptographically random and unguessable. A consumer that
   does not already hold a valid descriptor cannot fetch a result.
4. In production all MCP traffic uses HTTPS, so descriptors and tokens are
   confidential in transit.

Consequences:

1. The hub does not need descriptor signatures for v1.
2. Result GUIDs act as capabilities. Any registered service with hub-fetch
   activity, the right result-type capability, and the GUID may fetch the
   payload.
3. The hub does not enforce a per-end-user owner rule. This is deliberate: the
   gofr-agent controls which services exist, service calls are authenticated,
   GUIDs are unguessable, and production transport is HTTPS.
4. Descriptor metadata is not security input. Consumers and the hub use the
   hub-stored authoritative metadata returned by `_get_result` or
   `_describe_result`.
5. Prompt-injection-style content inside descriptor `summary` is bounded the
   same way as inline tool output when surfaced to the model.

The model can be hardened later with descriptor HMAC signing, stricter owner
checks, or a shared store without changing descriptor or tool shapes.

## Credential Provisioning

Hub-capable services need two auth relationships:

1. gofr-agent -> service: existing outbound service token in `ServiceConfig.token`
   or `ServiceConfig.token_env`.
2. service -> gofr-agent: callback credential used by the service to call
   `_store_result`, `_get_result`, and `_describe_result`.

The callback credential is a service-level bearer token provisioned by the auth
platform, preferably via Vault/bootstrap. The registration request must not send
secrets. A service receives its callback token through its own deployment config
(for example `GOFR_AGENT_HUB_TOKEN_ENV`).

For development fixtures, the same token may be used for both directions only if
it grants both downstream-tool activities and hub callback activities. Production
should prefer a dedicated callback token with the least activities needed by the
service.

The auth layer must let gofr-agent map a callback token to a stable service
principal. That principal is compared with the service registration record before
hub calls are accepted.

Required activities:

| Activity | Purpose |
|----------|---------|
| `GoFRAgentHubStore` | Allows a registered service to call `_store_result` |
| `GoFRAgentHubFetch` | Allows a registered service to call `_get_result` and `_describe_result` |
| `GoFRAgentHubRegister` | Optional internal activity for hub protocol registration paths |

End-user `ask` tokens must not receive these activities.

## Deployment Assumptions

The first implementation assumes:

1. exactly one gofr-agent process serves a given downstream stack;
2. the hub result store is process-local;
3. the hub URL is reachable from every downstream service;
4. development URLs use Docker service names on `gofr-net`;
5. production URLs use HTTPS DNS names or HTTPS service names reachable by the
   downstream services.

Multi-replica gofr-agent or cross-host deployment requires a shared store or
sticky GUID routing before this feature is enabled in that environment.

## Required Configuration

The hub URL is not optional when the hub is enabled.

| Setting | Description |
|---------|-------------|
| `GOFR_AGENT_HUB_ENABLED` | Master switch for the results hub |
| `GOFR_AGENT_HUB_URL` | MCP URL downstream services use to reach gofr-agent; must not be `localhost` or `127.0.0.1` |
| `GOFR_AGENT_HUB_DEFAULT_TTL_SECONDS` | Default result lifetime |
| `GOFR_AGENT_HUB_MAX_PAYLOAD_BYTES` | Maximum stored payload size |
| `GOFR_AGENT_HUB_MAX_RESULTS` | Maximum concurrent stored results |
| `GOFR_AGENT_HUB_PROTOCOL_VERSION` | Hub protocol version string |

gofr-agent refuses to advertise hub capability if `GOFR_AGENT_HUB_ENABLED` is
true and `GOFR_AGENT_HUB_URL` is unset or local-only.

## Reentrancy Requirement

A producer's downstream MCP call into gofr-agent runs while gofr-agent is still
awaiting that producer's tool response. The hub design requires that
gofr-agent's FastMCP server accepts inbound `_store_result` calls from the
producer in this state.

A Phase 0 spike must prove the real `_store_result` path works end-to-end with a
small payload, callback auth, store locking, descriptor creation, and bounded
latency. A no-op callback is not sufficient. If gofr-agent cannot safely service
reentrant inbound MCP calls, the design must be revisited.

## Protocol Tools

Hub protocol tools use exact reserved names and are not model-facing tools.
Do not hide arbitrary tools merely because they start with `_`.

Reserved protocol tool names:

| Tool | Exposed by | Model visible | Purpose |
|------|------------|---------------|---------|
| `_register_results_hub` | Downstream services | No | gofr-agent registers hub details and discovers capabilities |
| `_store_result` | gofr-agent | No | Producer stores a payload and receives a descriptor |
| `_get_result` | gofr-agent | No | Consumer fetches payload plus authoritative metadata |
| `_describe_result` | gofr-agent | No | Consumer fetches authoritative metadata without payload |

The registry should mark these tools as `model_visible = false` or filter these
exact names from model-facing surfaces. Other service tools keep their normal
visibility unless explicitly marked otherwise.

## Registration Flow

During service registration or refresh, gofr-agent lists downstream tools. If
`_register_results_hub` is present, gofr-agent calls it using the existing
outbound service identity.

Request shape:

| Field | Required | Description |
|-------|----------|-------------|
| `protocol_version` | Yes | Hub protocol version |
| `hub_service` | Yes | Logical hub name, normally `gofr-agent` |
| `hub_url` | Yes | URL downstream services use to reach gofr-agent |
| `store_tool` | Yes | Hub tool name, `_store_result` |
| `fetch_tool` | Yes | Hub tool name, `_get_result` |
| `describe_tool` | No | Hub tool name, `_describe_result` |
| `default_ttl_seconds` | Yes | Default result lifetime |
| `max_payload_bytes` | Yes | Maximum accepted payload size |
| `descriptor_kind` | Yes | Expected descriptor discriminator |

Response shape:

| Field | Required | Description |
|-------|----------|-------------|
| `accepted` | Yes | Whether the service accepted hub registration |
| `protocol_version` | Yes | Protocol version the service actually supports |
| `can_publish` | Yes | Service can call `_store_result` |
| `can_consume` | Yes | Service can call `_get_result` |
| `result_types` | Yes | Result types the service can publish or consume |
| `notes` | No | Optional bounded diagnostic text |

`result_types` may be represented as one list for v1, or split later into
`publish_result_types` and `consume_result_types` if producer and consumer
capabilities diverge.

gofr-agent rejects incompatible protocol versions and records accepted
capabilities in the service registry.

## Hub Tool Schemas

All hub tools return `McpError(ErrorData(...))` on failure. Error codes are
listed in the Error Model section.

### `_store_result`

Stores a JSON payload and returns a descriptor.

Request shape:

| Field | Required | Description |
|-------|----------|-------------|
| `protocol_version` | Yes | Must match the hub protocol version |
| `producer_service` | Yes | Registered service name claiming the payload |
| `producer_tool` | Yes | Tool that produced the payload |
| `result_type` | Yes | Semantic payload type, e.g. `ohlcv_bars` |
| `schema_id` | Yes | Payload schema identifier |
| `payload` | Yes | JSON-serialisable payload; no binary/blob data in v1 |
| `summary` | No | Bounded model-safe summary |
| `source_args` | No | Safe subset of source arguments |
| `ttl_seconds` | No | Requested TTL, capped by hub config |

Validation:

1. bearer token grants `GoFRAgentHubStore`;
2. token maps to the same registered service as `producer_service`;
3. service completed hub registration and `can_publish` is true;
4. `result_type` is in the service's registered result-type capability list;
5. payload size is at or below `GOFR_AGENT_HUB_MAX_PAYLOAD_BYTES`;
6. TTL is positive and capped by hub config;
7. protocol version is compatible.

Response shape:

| Field | Description |
|-------|-------------|
| `descriptor` | Result descriptor safe to return through the producer tool |

The response must not include the payload.

### `_get_result`

Fetches a JSON payload by GUID.

Request shape:

| Field | Required | Description |
|-------|----------|-------------|
| `protocol_version` | Yes | Must match the hub protocol version |
| `result_guid` | Yes | GUID from a descriptor |
| `hub_service` | Yes | Logical hub name from the descriptor |
| `expected_result_type` | No | Consumer's expected result type |
| `expected_schema_id` | No | Consumer's expected payload schema |

Validation:

1. bearer token grants `GoFRAgentHubFetch`;
2. token maps to a registered service that completed hub registration;
3. registered service `can_consume` is true;
4. result exists and has not expired;
5. if `expected_result_type` is supplied, it matches authoritative metadata;
6. if `expected_schema_id` is supplied, it matches authoritative metadata;
7. authoritative `result_type` is in the caller's registered result-type
   capability list;
8. protocol version is compatible.

Response shape:

| Field | Description |
|-------|-------------|
| `payload` | Stored JSON payload |
| `metadata` | Authoritative result metadata from the hub |

`metadata` includes `result_guid`, `result_type`, `schema_id`,
`producer_service`, `producer_tool`, `created_at`, `expires_at`, `payload_bytes`,
and optional `source_args`.

### `_describe_result`

Fetches authoritative metadata without returning payload.

Request shape is the same as `_get_result` except `expected_schema_id` is
optional and advisory for validation. Response shape contains only `metadata`.

## Result Descriptor Shape

The descriptor has structural fields and advisory fields. Structural fields are
required for parsing and routing. Advisory fields are useful for prompts,
debugging, and observability but must never be trusted for security or business
logic.

| Field | Class | Description |
|-------|-------|-------------|
| `kind` | structural | Discriminator, e.g. `gofr.result_ref` |
| `version` | structural | Descriptor schema version |
| `result_guid` | structural | Opaque unguessable result identifier |
| `hub_service` | structural | Logical hub name |
| `result_type` | advisory | Semantic type, e.g. `ohlcv_bars` |
| `schema_id` | advisory | Payload schema identifier |
| `producer_service` | advisory | Service that produced the payload |
| `producer_tool` | advisory | Tool that produced the payload |
| `created_at` | advisory | UTC creation timestamp |
| `expires_at` | advisory | UTC expiry timestamp |
| `summary` | advisory | Small bounded summary safe for model context |
| `source_args` | advisory | Safe subset of source arguments |
| `payload_bytes` | advisory | Approximate serialized payload size |

Consumers validate `kind`, `version`, `result_guid`, and `hub_service` before
calling the hub. They must rely on `_get_result.metadata` for authoritative
`result_type`, `schema_id`, and producer metadata.

Descriptors must not include service URLs, bearer tokens, secrets, or full
payload data. Descriptor `summary` content must be wrapped with the same
sentinel block convention used for inline tool output before being surfaced to
the model.

## Error Model

Hub tools use structured MCP errors. Initial error codes:

| Code | Meaning |
|------|---------|
| `hub.invalid_protocol_version` | Request protocol version is unsupported |
| `hub.unauthorised` | Bearer token is missing or lacks required activity |
| `hub.unregistered_service` | Token does not map to a registered hub-capable service |
| `hub.registration_required` | Service has not completed hub registration |
| `hub.result_type_not_allowed` | Service is not allowed to publish or consume this result type |
| `hub.unknown_result` | GUID does not exist |
| `hub.expired_result` | GUID exists but TTL has elapsed |
| `hub.oversized_result` | Payload exceeds max payload bytes |
| `hub.capacity_exceeded` | Store is at configured result-count limit |
| `hub.malformed_request` | Request shape is invalid |
| `hub.schema_mismatch` | Expected type or schema does not match authoritative metadata |

Error messages include recovery context but never include secrets or payload
content.

## Result Store

The hub result store is owned by gofr-agent.

Required behaviour:

1. generate opaque cryptographically random GUIDs;
2. store payload plus authoritative metadata;
3. enforce TTL;
4. enforce max payload size and total result count;
5. delete expired entries;
6. return structured errors for unknown, expired, oversized, unauthorised,
   malformed, and capability-denied requests.

First implementation is process-local. Multi-replica deployment requires a
shared store or sticky routing.

## Registry Capabilities

The service registry retains per-service hub capability metadata.

| Field | Description |
|-------|-------------|
| `supports_results_hub` | Service accepted hub registration |
| `can_publish_results` | Service can call `_store_result` |
| `can_consume_results` | Service can call `_get_result` and `_describe_result` |
| `result_types` | Result types the service may publish or consume |
| `registration_error` | Last hub registration failure |
| `model_visible` | Per-tool visibility flag used to hide protocol tools from the model |

This metadata is surfaced through `list_services` without exposing secrets.

## Tool Contract Model

Tools that consume large payloads migrate from inline payload arguments to
descriptor arguments.

| Current | Target |
|---------|--------|
| `bars: list[dict]` | `bars_ref: ResultDescriptor` |

During migration a consumer may temporarily accept both, but the descriptor path
is preferred in prompts and schemas once producer and consumer support the hub.
Once descriptor support is available for a workflow, the wrapper must not
auto-resolve inline payloads from the in-agent scratchpad for that workflow.

## Observability

Hub log and event fields:

| Field | Description |
|-------|-------------|
| `result_guid` | Correlates store and fetch operations |
| `request_id` | Current gofr-agent request id when available |
| `session_id` | Session id when available |
| `producer_service` | Payload producer |
| `consumer_service` | Payload consumer when known |
| `result_type` | Semantic payload type |
| `status` | stored / fetched / expired / denied / missing / oversized |
| `latency_ms` | Store/fetch latency |

Logs and events never include payloads or bearer tokens.

## Compatibility And Migration

1. Services without `_register_results_hub` continue to work as ordinary MCP
   services.
2. Existing inline-result tools continue to work while migrated workflows move
   to descriptors.
3. The current in-agent scratchpad may remain as a transitional fallback for
   workflows not yet migrated. It must not auto-resolve large payloads for
   workflows that have descriptor support.

## Initial Target Workflow

`instruments.get_ohlcv_history -> analytics simple_return / historical_volatility / max_drawdown`

1. `get_ohlcv_history` publishes OHLCV bars via `_store_result` and returns an
   `ohlcv_bars` descriptor.
2. Analytics tools accept `bars_ref`, call `_get_result` with
   `expected_result_type = ohlcv_bars`, validate authoritative metadata, then
   compute.
3. The model never sees the OHLCV array.

## Acceptance Criteria

1. Phase 0 reentrancy spike proves a downstream service can call the real
   `_store_result` path while gofr-agent is mid-tool-call.
2. `GOFR_AGENT_HUB_URL` is required when the hub is enabled and rejects
   local-only addresses.
3. Callback credential provisioning is implemented for fixtures and documented
   for production.
4. gofr-agent detects services exposing `_register_results_hub` and registers
   itself.
5. `_store_result`, `_get_result`, and `_describe_result` follow the schemas in
   this spec.
6. A producer can publish a large result and return a descriptor.
7. A consumer can fetch the referenced result by GUID and only trusts
   hub-returned authoritative metadata.
8. Auth, capability, TTL, size, descriptor-tamper, reentrancy, and validation
   failures are explicit and test-covered.
9. The AAPL OHLCV-to-analytics workflow succeeds without inline bars in model
   context.
