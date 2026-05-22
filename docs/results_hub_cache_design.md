# Results Hub Cache Design

## Purpose

`gofr-agent` currently stores results-hub payloads in process memory. That is fine
for unit tests and single-process demos, but it is fragile for UI sessions,
restarts, multiple workers, and any workflow where an MCP service stores a large
tool result and another service consumes it later through a descriptor.

The goal is to put an open source cache behind the results hub. The cache runs in
its own container on the same Docker network as `gofr-agent`. Downstream MCP
services still call gofr-agent hub tools (`_store_result`, `_get_result`,
`_describe_result`); only gofr-agent talks to the cache.

## Requirements

- Preserve the existing hub protocol and descriptor shape.
- Keep descriptors session-neutral: descriptors must not carry raw `session_id`.
- Keep the in-memory store as the default test fallback.
- Add a production-like cache backend that supports TTL expiry.
- Run the cache as its own container on `gofr-net` or the active fixture network.
- Never expose cache credentials or payloads in logs.
- Keep hub storage bounded by TTL, maximum payload size, and explicit hub
  capacity rules.
- Support fast `store`, `get`, and `describe` by `result_guid`.
- Scope all hub reads and writes to the originating `session_id`.
- Make cache health visible in startup logs and `health_check` output.
- Fail closed on cache errors: return structured hub errors, do not silently fall
  back to in-memory storage after startup.

## Option Review

### Valkey

Valkey is the Linux Foundation fork of Redis, BSD licensed, actively maintained,
and API-compatible for the Redis commands this feature needs. It has first-class
TTL support, good Docker images, mature clients, and simple operational behavior.

Pros:
- Open source governance and permissive licensing.
- Redis protocol compatibility keeps Python client options mature.
- Native key TTL fits descriptor expiry exactly.
- Low latency and simple deployment as one container.
- Supports memory limits and eviction policies.

Cons:
- Mostly in-memory, so payload size and retention must remain bounded.
- Phase 1 is intentionally volatile-only, so descriptors do not survive cache
  restart.
- Requires a new dependency and connection lifecycle management.

### Redis Community Edition

Redis remains operationally familiar and technically suitable. It supports the
same TTL and key-value model. The main concern is licensing/governance for future
use; if the goal is explicitly open source cache infrastructure, Valkey is the
cleaner default.

Pros:
- Very mature and widely understood.
- Excellent Python client support.
- Same technical fit as Valkey for this use case.

Cons:
- Licensing/governance is less straightforward than Valkey for an OSS-first
  platform decision.
- Choosing Redis now may force a later policy decision if distribution changes.

### Dragonfly

Dragonfly is Redis-protocol compatible and fast. It is attractive for high
throughput, but the current hub workload is not CPU-bound or cache-engine-bound.
The extra performance is not needed yet.

Pros:
- Redis-compatible protocol.
- Strong throughput and memory efficiency.
- Simple container deployment.

Cons:
- Less conservative operational choice for this repo today.
- Smaller ecosystem than Redis/Valkey.
- Performance benefits do not address the current reliability gap.

### KeyDB

KeyDB is Redis-compatible and open source. It is capable, but less aligned with
current ecosystem momentum than Valkey.

Pros:
- Redis-compatible protocol.
- Mature enough for cache workloads.

Cons:
- Smaller community and less obvious long-term default than Valkey.
- No major advantage for this hub use case.

### Memcached

Memcached is simple and fast, but it is a weaker fit because the hub benefits
from storing structured metadata and payloads together, using precise TTLs, and
having richer introspection options.

Pros:
- Very simple operational model.
- Fast key-value TTL cache.

Cons:
- Less expressive than Redis-compatible stores.
- No native structured types if later needed.
- Weaker path for future diagnostics and storage evolution.

## Recommendation

Use Valkey as the primary cache backend.

Valkey gives the best balance for this project: genuinely open source, familiar
Redis protocol, low operational complexity, native TTLs, and a clean container
story. It solves the immediate hub reliability problem without making agent
memory or larger storage choices prematurely.

Keep the existing in-memory `ResultStore` for tests and minimal dev mode. Add a
pluggable store interface and an external-cache adapter selected by
configuration. The phase-1 external-cache adapter implementation uses Valkey,
but the core-facing backend name is `external_cache`.

For phase 1, the Valkey-backed hub is explicitly volatile-only. No RDB snapshots,
no AOF, and no attempt to recover hub payloads after cache restart. That matches
the hub's role as a bounded handoff cache rather than durable storage.

The boundary must be interface-based. Core `gofr-agent` code should depend only
on a hub store protocol and generic health/status models. Valkey-specific client
code, topology handling, retry behavior, and connection management must stay
inside the backend adapter layer.

## Proposed Architecture

```text
Downstream MCP service
  -> calls gofr-agent _store_result/_get_result/_describe_result
  -> gofr-agent validates auth, resolves session scope, validates protocol and quotas
  -> HubResultStore interface bound to session_id
  -> HubStoreFactory-selected adapter
  -> cache service
```

Downstream services receive descriptors and continue using the existing hub
tools. The LLM never receives cache credentials or direct cache access.

`gofr-agent` core should not know whether the backing store is memory, Valkey,
or another implementation. Outside option-review and deployment docs, core-facing
configuration, health, and startup logs should use `memory` or `external_cache`.
Only the backend adapter and store factory should know concrete backend details.

Hub isolation rule: every stored result belongs to exactly one `session_id`.
Descriptors are only valid inside that originating session. A descriptor copied
into another session must not resolve.

## Abstraction Boundary

Define a protocol such as `HubResultStore` with only generic operations:

- `store(scope, request) -> ResultDescriptor`
- `get(scope, request) -> GetResultResponse`
- `describe(scope, request) -> DescribeResultResponse`
- `health() -> HubStoreHealth`
- optional lifecycle hooks such as `start()` and `stop()`

Define a generic `HubAccessScope` model with at least:

- `session_id`: originating gofr-agent session
- `session_namespace`: opaque keyed namespace derived from `session_id`
- `request_id`: optional request/run correlation
- `run_id`: optional agent run correlation
- `principal_service`: service principal performing the hub call
- `allowed_operations`: allowed hub operations such as `store`, `get`, `describe`
- `allowed_result_types`: result types the principal may publish or consume

Also define a generic `HubStoreHealth` model that reports fields like:

- `backend`: `memory` or `external_cache`
- `status`: `healthy`, `degraded`, or `failed`
- `reachable`: boolean
- `error`: bounded text or `None`

Important design rule: modules like `app/mcp_server/mcp_server.py`,
`app/main_mcp.py`, `app/health.py`, and the hub protocol models must not import
Valkey/Redis client types directly. Backend-specific knowledge belongs in
`store_factory` and the backend adapter module only.

Important session-isolation rule: `session_id` must be resolved by gofr-agent
from trusted session context, not accepted as an arbitrary caller-supplied field
from downstream MCP services or from the cache backend.

## Session Isolation

The hub must be session-id specific end to end.

That means two separate requirements:

1. The internal store interface is session-scoped.
2. The callback path from downstream services back into the hub is also
   session-scoped.

The current static per-service callback token model is not sufficient for strong
session isolation because the same service principal may participate in many user
sessions. The design therefore requires a session-bound hub access mechanism.

Phase-1 rule:

- gofr-agent must mint a signed, short-lived, session-bound hub callback token
  for each active ask session and downstream service call that may use the hub
- downstream hub callbacks must present that token
- gofr-agent resolves `session_id` from that trusted context before calling
  `HubResultStore`
- raw `session_id` from downstream callers is never trusted on its own

Phase 1 uses a signed hub callback token. The token is minted by gofr-agent and
validated only by gofr-agent hub tools. It must not be generated by the LLM or by
downstream services.

Required token claims:

- `iss`: `gofr-agent`
- `aud`: `gofr-agent-hub`
- `service`: downstream service principal
- `session_namespace`: opaque keyed namespace derived from `session_id`
- `ops`: allowed hub operations, for example `store`, `get`, `describe`
- `result_types`: allowed result types for that service
- `request_id` and `run_id`: correlation values when available
- `iat`, `nbf`, `exp`, and `jti`

The callback token should be signed with an existing trusted auth signing path or
a dedicated hub signing key loaded from the same secret-management plane. Default
token TTL should be short, for example 10 minutes, and capped by the active run
or pending prompt lifetime where applicable.

The service-facing token should prefer `session_namespace`, not raw `session_id`.
If gofr-agent needs the raw session ID after token validation, it should resolve
it from trusted in-process run/session context or from a server-side mapping keyed
by `jti` or `session_namespace`. Do not require downstream services to receive or
echo raw session IDs.

Downstream services receive session-bound hub context per tool call, not through
global startup registration. Startup registration remains a capability discovery
step: it tells gofr-agent whether a service can publish or consume hub results.
At runtime, the tool wrapper supplies per-call hub context to the downstream MCP
session.

Preferred transport:

- `X-GOFR-HUB-URL`: gofr-agent hub URL
- `X-GOFR-HUB-CALLBACK-TOKEN`: signed session-bound callback token

If MCP transport or a downstream framework cannot expose request headers to tool
code, the fallback is a reserved, gofr-agent-injected hub context envelope that
is not model-generated and is not part of the public tool schema. Services that
cannot receive per-call session-bound hub context must not use descriptor mode
for session-scoped hub data.

Cross-session lookups must fail closed. Prefer returning `HUB_UNKNOWN_RESULT` or
another non-revealing isolation error rather than confirming that a descriptor
exists in some other session.

## Adapter-Internal Data Model

The phase-1 external-cache adapter uses three cache structures per hub namespace:

```text
gofr-agent:hub:session:{session_namespace}:meta:{result_guid}
gofr-agent:hub:session:{session_namespace}:payload:{result_guid}
gofr-agent:hub:session:{session_namespace}:index
```

Metadata value is canonical JSON:

```json
{
  "session_namespace": "...",
  "result_guid": "...",
  "result_type": "ohlcv_bars",
  "schema_id": "gofr.ohlcv_bars.v1",
  "producer_service": "instruments",
  "producer_tool": "get_ohlcv_history",
  "created_at": "...",
  "expires_at": "...",
  "payload_bytes": 1234,
  "summary": "31 OHLCV bars for MSFT",
  "source_args": {"ticker": "MSFT"}
}
```

Payload value is canonical JSON for the stored payload only.

`gofr-agent:hub:session:{session_namespace}:index` is a sorted set keyed by
`result_guid` with `expires_at_epoch_seconds` as the score.

This layout is adapter-internal and deliberately hidden behind `HubResultStore`:

- every session gets its own isolated key namespace
- `describe` can read metadata without loading the payload.
- `get` can fetch both metadata and payload.
- the sorted-set index gives the hub a way to prune expired records and enforce
  `hub_max_results` within one session without scanning the entire keyspace.
- the index also provides a foundation for health and diagnostics.

Set the same TTL on both `meta` and `payload` keys. The hub should still validate
`expires_at` after read so behavior is correct even if TTL precision or clock
drift differs slightly.

The adapter should assume it owns a dedicated key prefix and preferably a
dedicated logical DB. It must never rely on global `DBSIZE` or broad key scans.

`session_namespace` must be a keyed, non-reversible namespace derived from
`session_id`, for example `base64url(HMAC(hub_namespace_secret, session_id))`.
Raw session IDs must not appear in cache keys, cache values used for routing,
metrics, or operational logs.

`hub_max_results` should be treated as a per-session bound, not a global shared
bucket across unrelated sessions.

## Configuration

Add these settings to `GofrAgentConfig`:

| Env var | Default | Purpose |
|---------|---------|---------|
| `GOFR_AGENT_HUB_STORE_BACKEND` | `memory` | `memory` or `external_cache` |
| `GOFR_AGENT_HUB_CACHE_URL` | unset | Opaque external-cache URL consumed only by the adapter, for example `redis://gofr-agent-valkey:6379/0` |
| `GOFR_AGENT_HUB_CACHE_CONNECT_TIMEOUT_SECONDS` | `1` | Cache connect timeout |
| `GOFR_AGENT_HUB_CACHE_OPERATION_TIMEOUT_SECONDS` | `2` | Per-command timeout |
| `GOFR_AGENT_HUB_CACHE_MAX_ATTEMPTS` | `2` | Maximum attempts per cache operation, including the first attempt |
| `GOFR_AGENT_HUB_CACHE_RETRY_BACKOFF_SECONDS` | `0.2` | Initial bounded retry backoff |
| `GOFR_AGENT_HUB_CACHE_REQUEST_BUDGET_SECONDS` | `5` | Maximum wall-clock budget for one cache operation |
| `GOFR_AGENT_HUB_CACHE_KEY_PREFIX` | `gofr-agent:hub` | Key namespace |
| `GOFR_AGENT_HUB_CACHE_MEMORY_BUDGET_BYTES` | `268435456` | Expected cache memory budget used for startup capacity validation |
| `GOFR_AGENT_HUB_CACHE_ACTIVE_SESSION_BUDGET` | `20` | Expected maximum active hub sessions for memory budget validation |
| `GOFR_AGENT_HUB_CALLBACK_TOKEN_TTL_SECONDS` | `600` | Maximum lifetime for session-bound hub callback tokens |
| `GOFR_AGENT_HUB_CACHE_HEALTHCHECK_INTERVAL_SECONDS` | `30` | Background cache health probe cadence |

When `GOFR_AGENT_HUB_STORE_BACKEND=external_cache`, startup must require
`GOFR_AGENT_HUB_CACHE_URL`. If the cache is unreachable, startup should fail
before the server accepts requests. Do not start with `hub_enabled=true` and a
selected `external_cache` backend that is unavailable.

Startup should also validate the configured cache memory budget against hub
limits. At minimum, compute
`hub_cache_active_session_budget * hub_max_results * hub_max_payload_bytes` and
fail fast if the theoretical payload budget exceeds a safe fraction of
`GOFR_AGENT_HUB_CACHE_MEMORY_BUDGET_BYTES`. A conservative target is 70 percent
to leave room for metadata, index overhead, allocator overhead, and protocol
buffers. The real-server external-cache profile must set `hub_max_results`,
`hub_max_payload_bytes`, active-session budget, and cache memory to a consistent
set of values.

## Container

Add a Valkey service to the dev stack used with the real agent. This should be
the default local development shape so dev and prod share the same hub-storage
topology: gofr-agent in one container, Valkey in another.

```yaml
services:
  valkey:
    image: valkey/valkey:8-alpine
    container_name: gofr-agent-valkey
    hostname: gofr-agent-valkey
    command:
      - valkey-server
      - --save
      - ""
      - --appendonly
      - "no"
      - --maxmemory
      - 256mb
      - --maxmemory-policy
      - noeviction
    networks:
      - gofr-net
    healthcheck:
      test: ["CMD", "valkey-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10
```

For local real-server runs:

```bash
docker compose -f docker/compose.dev.yml --profile runtime up -d --build
```

The image and service name can be parameterized later, but the first
implementation should keep the container boring and explicit.

`noeviction` is important. The hub contract should not silently evict a stored
result before its descriptor expires. If memory pressure occurs, writes should
fail explicitly and surface a structured capacity error instead of causing random
future descriptor misses.

This cache is intentionally volatile-only. The container should start without
RDB snapshots and without AOF. If the container restarts, outstanding descriptors
may become invalid and should fail as unknown results.

## Backend Resilience

Adopt basic resilience capabilities, but keep them hidden from `gofr-agent`
core behind the backend adapter.

Phase 1 backend resilience should include:

- connection pooling managed by the adapter client
- connect and operation timeouts
- bounded retry with backoff for cache operations, connection establishment, and
  health probes
- automatic reconnect after transient disconnects
- periodic health probing surfaced only through `HubStoreHealth`
- atomic write semantics for `store`

These behaviors should be implemented in the Valkey adapter or its client
wrapper, not in the MCP server or hub business logic.

Default request-path resilience budget:

- at most 2 attempts total, including the first attempt
- at most 1 second to connect
- at most 2 seconds per cache command
- at most 5 seconds wall-clock for one hub store/get/describe operation
- no background health probe may block request handling

The adapter may mask brief reconnect churn inside that budget, but it must return
a structured dependency failure once the budget is exhausted.

If later phases adopt Valkey replication, Sentinel, or another managed
topology, that support must also stay behind the same `HubResultStore`
interface. `gofr-agent` core should see only a healthy or unhealthy external
store, never backend-specific topology objects.

## Code Changes

1. Define a store protocol, for example `HubResultStore`, plus a generic
  `HubStoreHealth` model and a `HubAccessScope` model that includes
  `session_id`.
2. Keep the current in-memory implementation behind that protocol.
3. Add an external-cache backend adapter. The first implementation can live in
  `app/hub/external_cache_store.py` and use a private Valkey client wrapper
  internally.
4. Add `create_result_store(config)` in `app/hub/store_factory.py` and confine
  all backend selection logic there.
5. Thread existing gofr-agent `session_id` through the hub call path so store
  operations always receive trusted session scope.
6. Replace static service-only hub callback context with signed session-bound hub
  callback tokens suitable for downstream callbacks.
7. Inject session-bound hub callback context into downstream MCP tool calls via
  request headers, with a reserved non-model-generated hub context fallback only
  where headers are unavailable.
8. Update `create_mcp_server(...)` to accept the created store as it does today,
  but have `main_mcp` build the store explicitly during startup.
9. Keep Valkey-specific connection pooling, retry/backoff, reconnect, and
  health-probe behavior inside the backend adapter or a small client wrapper.
10. Add startup validation that logs generic backend health and failure reason
  without logging credentials.
11. Add health payload fields sourced from `HubStoreHealth`, not from backend-
  specific client types.
12. Add focused tests for memory and external-cache behavior. Use a fake async
  cache client for unit tests and container-backed Valkey integration tests
  where available.
13. Use an atomic write path for `store` so the hub never creates a descriptor
   if only some of `meta`, `payload`, or `index` were written. A small Lua
   script or `WATCH/MULTI/EXEC` sequence is acceptable.

## Validation Rules

The external-cache store should preserve existing hub behavior:

- Reject or fail closed when trusted session scope is missing.
- Reject unsupported protocol versions.
- Reject non-positive TTLs.
- Cap requested TTL at `hub_default_ttl_seconds`.
- Reject non-JSON-serializable payloads and source args.
- Enforce `hub_max_payload_bytes` before writing.
- Enforce `hub_max_results` per session via the session-scoped sorted-set index
  after pruning expired entries.
- Return `HUB_UNKNOWN_RESULT` for missing keys.
- Return `HUB_EXPIRED_RESULT` if metadata says the result is expired.
- Enforce expected result type and schema on `get` and `describe`.
- Clean up stale index entries when `meta` or `payload` is missing.
- Return `HUB_UNKNOWN_RESULT` or another non-revealing isolation failure when a
  descriptor is presented from the wrong session.
- Verify callback token claims before creating `HubAccessScope`: audience,
  expiry, service principal, allowed operations, result types, and session scope.
- Keep `ResultDescriptor` session-neutral. Do not add raw `session_id` or
  `session_namespace` to the descriptor.

## Failure Behavior

Startup failures:
- If backend is `external_cache`, hub is enabled, and the cache is unreachable:
  fail fast.
- If backend is `memory`: no external health check is required.

Runtime failures:
- Connection timeout or dependency outage: return a structured hub error with a
  cache-unavailable code.
- Adapter-level retries must be bounded and short. The adapter may mask brief
  reconnect churn, but it must not turn a dead cache into long request hangs.
- Session-scope mismatch or missing session-bound callback context: fail closed
  without revealing whether a descriptor exists in another session.
- Missing, expired, malformed, or wrong-audience callback token: fail closed
  before store access.
- Serialization failure: return malformed-request or oversized-result errors as
  today.
- Cache write rejected for memory pressure: return `HUB_CAPACITY_EXCEEDED` and
  log `hub_store_capacity_reached`.
- Partial key loss or operator-driven cache flush: return unknown-result,
  clean up stale index entries, and log `hub_store_inconsistent_record`.

Add a new hub error code for cache dependency failures, for example
`HUB_STORE_UNAVAILABLE`, so clients can distinguish dependency failure from bad
descriptors.

## Security

- Do not expose the cache service outside the Docker network by default.
- Do not log full cache URLs if credentials are embedded.
- Prefer no password for local dev network-only containers; support passworded
  URLs for shared environments.
- Keep all auth decisions in gofr-agent. The cache is not an authorization
  boundary.
- Treat session binding as an authorization boundary for hub data access.
- Continue to validate producer/consumer hub registration before any cache read
  or write.

## Observability

Startup log should include:

```text
hub_store_backend=external_cache
hub_cache_url_configured=True
hub_cache_status=healthy
hub_cache_dependency=external-cache:6379
```

Health output should include the same fields plus bounded error text when
unhealthy. Store/get/describe logs should include result type, payload bytes,
TTL, keyed session fingerprint, and result GUID fingerprint, not the full
payload.

Health should also report whether the backend is `memory` or `external_cache`,
whether the cache dependency is reachable, and the live indexed result count
observed via the hub prefix. Indexed result counts should be reported per
session where relevant, or as bounded aggregates that do not expose other
session identifiers.

These health fields should come from the generic store-health interface, not
from backend-specific status objects exposed to the rest of the application.

## Rollout Plan

1. Add config and store protocol with no behavior change.
2. Move current `ResultStore` behind the protocol and keep all tests passing.
3. Add session-scoped hub access models and thread trusted `session_id` through
  the hub boundary.
4. Add signed session-bound hub callback tokens and per-call downstream context
   injection.
5. Add the external-cache implementation and unit tests with a fake client.
6. Add the session-scoped indexed key layout and atomic store semantics.
7. Add Valkey container to the dev stack used for the real agent so local dev
  mirrors the production deployment model.
8. Add integration tests for store/get/describe through the MCP hub tools,
   including stale-key and startup-failure cases.
9. Add cross-session isolation tests proving that descriptors from one session
  cannot be resolved from another session.
10. Add callback-token tests for expiry, wrong audience, wrong service, wrong
   operation, wrong result type, and missing session scope.
11. Enable `external_cache` in the real-server dev flow by default; keep memory
  backend for tests and explicit lightweight runs only.
12. Update README and health docs.

## Decision

Use Valkey first as the implementation behind the `external_cache` adapter. Keep
Redis-compatible URLs and client code isolated in the adapter so Redis,
Dragonfly, or KeyDB can be swapped in later if operations require it. Phase 1 is
volatile-only and runs as a separate Valkey container in the dev stack so local
development matches the intended production shape. Do not build agent memory
until the hub has stable external storage, health checks, and failure semantics.