# MCP Results Hub Implementation Plan

Status: COMPLETE (validated 2026-05-16)
Spec: `docs/archive/mcp_artifact_handoff_spec.md`
Downstream participant spec: `docs/archive/results_hub_mcp_server_spec.md`

## Read This First

This plan is intentionally detailed. Follow it in order. Do not jump ahead,
combine phases, or simplify the design to make a local test pass.

All commands run from the repository root. Use `uv` and `./scripts/run_tests.sh`
only. Do not run raw `pytest`, do not use `pip`, and do not use `localhost` or
`127.0.0.1` for service-to-service URLs.

Do not `git add`, `commit`, or `push` unless explicitly asked.

## Pinned Names And Constants

Do not invent alternatives for these names; the plan and code must agree.

Env vars:

- `GOFR_AGENT_HUB_ENABLED`
- `GOFR_AGENT_HUB_URL`
- `GOFR_AGENT_HUB_DEFAULT_TTL_SECONDS`
- `GOFR_AGENT_HUB_MAX_PAYLOAD_BYTES`
- `GOFR_AGENT_HUB_MAX_RESULTS`
- `GOFR_AGENT_HUB_PROTOCOL_VERSION`
- `GOFR_FIXTURES_HUB_CALLBACK_TOKEN` - fixture's outbound callback token
- `GOFR_AGENT_HUB_CALLBACK_TOKEN` - optional default callback token for any
  in-process gofr-agent helper that calls its own hub during tests

Fixed dev token literals (used only in dev/CI through `DevAuthService`):

- `dev-admin-token` - existing
- `dev-read-token` - existing
- `dev-fixtures-hub-token` - new; granted only `GoFRAgentHubStore` and
  `GoFRAgentHubFetch`

Reserved hub protocol tool names:

- `_register_results_hub` - on downstream services
- `_store_result`, `_get_result`, `_describe_result` - on gofr-agent

Descriptor / protocol identifiers:

- `descriptor.kind`: `gofr.result_ref`
- `descriptor.version`: `1`
- `protocol_version`: `1`
- Initial `result_type`: `ohlcv_bars`
- Initial `schema_id`: `gofr.ohlcv_bars.v1`

GUIDs:

- `secrets.token_urlsafe(32)`. Do not use `uuid4()`, do not use sequential ids.

Payload size measurement (used identically in store, producer precheck, and
tests):

```
json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
```

Descriptor-enabled tool detection:

- A tool argument is descriptor-enabled iff its JSON schema includes
  `"x-gofr-result-descriptor": true`. The agent wrapper must use this exact
  marker to decide whether to skip scratchpad enrichment for that argument.
  Do not pattern-match on field names like `bars_ref`.

## Design Invariants

The implementation must preserve these rules throughout every phase:

1. gofr-agent is the results hub. Downstream services never call each other.
2. The model sees descriptors only. It must never receive large result payloads.
3. Hub protocol tools are exact reserved names: `_register_results_hub`,
   `_store_result`, `_get_result`, `_describe_result`.
4. Hide only reserved protocol tools or tools explicitly marked
   `model_visible = false`. Do not hide every tool whose name starts with `_`.
5. Phase 0 must prove the real `_store_result` callback path. A no-op callback
   is not acceptable.
6. Callback credentials are service-level bearer tokens. End-user `ask` tokens
   must not receive hub-store or hub-fetch activities.
7. V1 token-to-service mapping is explicit: add optional
   `hub_callback_token` / `hub_callback_token_env` fields to `ServiceConfig`,
   resolve them like existing service tokens, and compare callback tokens to
   registered services without logging token values.
8. Callback tokens are not sent in `_register_results_hub` requests or returned
   by `list_services`.
9. `kind`, `version`, `result_guid`, and `hub_service` are structural descriptor
   fields. Consumers validate them before hub fetch.
10. `result_type`, `schema_id`, producer metadata, timestamps, summary,
   `source_args`, and `payload_bytes` are advisory in descriptors.
11. Consumers trust `_get_result.metadata`, not advisory descriptor fields.
12. Registered `result_types` are enforced on publish and fetch.
13. No per-end-user owner rule is added in v1.
14. Result GUIDs are cryptographically random and treated as capabilities.
15. No descriptors, logs, errors, events, or service-list responses include
   payloads, bearer tokens, or secrets.
16. The first implementation is single-process and process-local. Do not add a
   distributed store in this plan.
17. The existing in-agent scratchpad remains only for legacy non-descriptor
   workflows. It must not auto-substitute payloads for descriptor-enabled
   workflows.

If any implementation choice conflicts with these invariants, stop and update
this plan/spec with user approval before coding further.

## Standard Phase Workflow

Each phase follows this order:

1. Read the relevant spec section and this phase's checklist.
2. Run `git --no-pager status --short` and identify unrelated user changes.
3. Run the phase's targeted tests before editing if they already exist.
4. Add or update tests for the phase's new behaviour first.
5. Run the new targeted tests and confirm they fail for the expected reason.
6. Implement the smallest code needed for that phase.
7. Run the targeted tests until they pass.
8. Run code-quality checks.
9. Run the full suite.
10. Update this plan's checkpoint log for the phase.

Required validation commands after each phase:

```
./scripts/run_tests.sh <phase-specific test files> -v
./scripts/run_tests.sh -v
```

`./scripts/run_tests.sh -v` already runs the code-quality gate first, so do not
add a separate quality invocation unless you are iterating on lint/type fixes
- in that case use `./scripts/run_tests.sh --quality`.

Prefer file-scoped runs over `-k` for the targeted step. Use `-k` only when you
need a narrow keyword inside a file (for example `-k "oversize"`). Coarse
selectors like `-k tool_factory` will silently include unrelated tests.

If the full suite fails, do not proceed to the next phase. Diagnose the failure.
If it is clearly unrelated and cannot be safely fixed within the phase, stop and
ask before widening scope.

## Checkpoint Log

Update this table during implementation. Do not mark a phase done until its
full validation set passes.

| Phase | Status | Required Evidence |
|-------|--------|-------------------|
| 0a | COMPLETE | Hub config/auth/callback-token coverage implemented; final `./scripts/run_tests.sh -v` passed |
| 0b | COMPLETE | Real `_store_result` reentrancy coverage implemented; final `./scripts/run_tests.sh -v` passed |
| 1 | COMPLETE | Protocol model/error coverage implemented; final `./scripts/run_tests.sh -v` passed |
| 2 | COMPLETE | Store TTL/capacity/bounds coverage implemented; `tmp/remediation_slice.txt` and final full suite passed |
| 3 | COMPLETE | Hub tool auth/filtering coverage implemented; final `./scripts/run_tests.sh -v` passed |
| 4a | COMPLETE | Hub registration integration coverage implemented; final `./scripts/run_tests.sh -v` passed |
| 4b | COMPLETE | `list_services` capability/no-secret coverage implemented; final `./scripts/run_tests.sh -v` passed |
| 5 | COMPLETE | Descriptor-producing instruments path implemented; final `./scripts/run_tests.sh -v` passed |
| 6 | COMPLETE | Descriptor-consuming analytics path and negative-path coverage implemented; final `./scripts/run_tests.sh -v` passed |
| 7 | COMPLETE | Descriptor passthrough/prompt guidance coverage implemented; final `./scripts/run_tests.sh -v` passed |
| 8 | COMPLETE | End-to-end descriptor workflow and negative paths green; `tmp/fixture_chat_final.txt` passed in descriptor mode |
| Review remediation | COMPLETE | `tmp/remediation_slice.txt`, `tmp/nodeid_after_fix.txt`, and final `./scripts/run_tests.sh -v` passed |
| 9 | COMPLETE | Docs/examples updated; grep checks, `./scripts/run_tests.sh --quality`, and final `./scripts/run_tests.sh -v` passed |

Evidence artefacts generated during final validation:

- `tmp/remediation_slice.txt`
- `tmp/nodeid_after_fix.txt`
- `tmp/quality_final.txt`
- `tmp/full_suite_final.txt`
- `tmp/fixture_chat_final.txt`

## Phase 0a - Config, Permissions, And Callback Token Plumbing

Purpose: introduce the configuration, permission, and callback-token surface
that the rest of the work depends on, without any new MCP tools yet.

Files likely touched:

| File | Why |
|------|-----|
| `app/config.py` | Hub config fields and URL validation |
| `app/auth/permissions.py` | Hub activity constants |
| `app/auth/_dev_auth_service.py` | `dev-fixtures-hub-token` with only hub activities |
| `app/auth/__init__.py` | Re-export `AGENT_HUB_*` if existing pattern requires it |
| `app/services/__init__.py` | `hub_callback_token` / `hub_callback_token_env` on `ServiceConfig` |
| `app/hub/__init__.py` | New package |
| `app/hub/auth.py` | `ServicePrincipal` and `resolve_service_principal(token, registry)` helper |
| `tests/unit/test_config.py` | Hub config validation |
| `tests/unit/test_auth_permissions.py` | Hub activity constants |
| `tests/unit/test_services_models.py` | Callback token env resolution and non-leakage |
| `tests/unit/test_hub_auth.py` | Token-to-service-principal mapping |

Tests to add first:

1. `tests/unit/test_config.py`
   - default `hub_enabled` is false;
   - `hub_enabled=true` without `hub_url` is invalid;
   - `hub_url` rejects `http://localhost:8090/mcp`,
     `http://127.0.0.1:8090/mcp`, and `http://[::1]:8090/mcp`;
   - `hub_url` accepts `http://gofr-agent:8090/mcp` for dev;
   - `hub_url` accepts an HTTPS DNS/service URL for production;
   - env parsing works for `GOFR_AGENT_HUB_*` values.
2. `tests/unit/test_auth_permissions.py`
   - `AGENT_HUB_STORE`, `AGENT_HUB_FETCH`, and optional `AGENT_HUB_REGISTER`
     string constants exist with values `GoFRAgentHubStore`,
     `GoFRAgentHubFetch`, `GoFRAgentHubRegister`;
   - if existing convention requires `ALL_ACTIVITIES` to enumerate every
     known activity, the new ones are included;
   - `dev-admin-token` and `dev-read-token` do not grant hub activities;
   - `dev-fixtures-hub-token` grants only `AGENT_HUB_STORE` and
     `AGENT_HUB_FETCH`.
3. `tests/unit/test_services_models.py`
   - `hub_callback_token_env` resolves from env like `token_env`;
   - explicit `hub_callback_token` takes precedence over env;
   - missing callback token is allowed for non-hub services;
   - `model_dump()` of `ServiceConfig` excludes the resolved callback token
     value when called with a `safe=True` flag (or equivalent helper used by
     `list_services`).
4. `tests/unit/test_hub_auth.py`
   - `resolve_service_principal(token, registry)` returns `None` for unknown
     tokens;
   - returns the matching `ServicePrincipal` (service name, registered
     `result_types`, `can_publish`, `can_consume`) for a token registered as
     a service callback token;
   - uses `secrets.compare_digest` semantics (no early return on length);
   - never logs the raw token value.

Implementation steps:

1. Add config fields to `GofrAgentConfig`: `hub_enabled`, `hub_url`,
   `hub_default_ttl_seconds`, `hub_max_payload_bytes`, `hub_max_results`,
   `hub_protocol_version`.
2. Validate config in `GofrAgentConfig.from_env()` or pydantic validators.
   Reject local-only hub URLs when `hub_enabled` is true.
3. Add hub permission constants in `app/auth/permissions.py`:
   `AGENT_HUB_STORE = "GoFRAgentHubStore"`,
   `AGENT_HUB_FETCH = "GoFRAgentHubFetch"`, optional
   `AGENT_HUB_REGISTER = "GoFRAgentHubRegister"`. Add to `ALL_ACTIVITIES` only
   if the existing convention requires it.
4. Update `DevAuthService` with `dev-fixtures-hub-token` mapped to the two hub
   activities and nothing else.
5. Extend `ServiceConfig` with optional `hub_callback_token` and
   `hub_callback_token_env`, resolved by the existing `_resolve_token_env`
   model validator. Add a `safe_dump()` (or equivalent) that excludes both
   `token` and `hub_callback_token` for use by `list_services` and logs.
6. Implement `app/hub/auth.py` with `ServicePrincipal` (service name,
   `result_types`, `can_publish`, `can_consume`) and
   `resolve_service_principal(token: str, registry: ServiceRegistry) -> ServicePrincipal | None`.
   The lookup must walk the registry's hub-capable services, compare callback
   tokens with `secrets.compare_digest`, and never include token values in
   logs. This helper is the single source of truth used by all hub tools.
7. Add `tests/code_quality/test_code_quality.py::MIGRATED_LOGGING_FILES`
   entries for any new `app/hub/*.py` modules introduced in this phase.

Validation commands:

```
./scripts/run_tests.sh tests/unit/test_config.py tests/unit/test_auth_permissions.py tests/unit/test_services_models.py tests/unit/test_hub_auth.py -v
./scripts/run_tests.sh -v
```

Phase 0a checkpoint: COMPLETE (validated 2026-05-16)

- Hub config fields are typed and validated.
- Hub activities exist and are not granted to ordinary tokens.
- `ServiceConfig` carries callback token info but never leaks it.
- `resolve_service_principal` works deterministically.
- Full suite passes.
- Evidence: final validation finished cleanly through `./scripts/run_tests.sh -v`; see the Checkpoint Log and `tmp/full_suite_final.txt`.

## Phase 0b - Real `_store_result` Reentrancy Spike

Purpose: prove the hardest runtime assumption before building the rest. A
fixture service must call the real `_store_result` path while gofr-agent is
still waiting for that fixture tool response.

Files likely touched:

| File | Why |
|------|-----|
| `app/hub/models.py` | Minimal final-shaped store request/descriptor models |
| `app/hub/store.py` | Minimal final-shaped in-process store |
| `app/hub/errors.py` | Minimal final-shaped error helpers used by the spike |
| `app/mcp_server/mcp_server.py` | Register `_store_result` hub tool with final-shape behaviour |
| `docker/mcp_fixtures/serve.py` | Reentrant producer spike tool |
| `docker/compose.fixtures.yml` | Inject `GOFR_FIXTURES_HUB_CALLBACK_TOKEN` and `GOFR_AGENT_HUB_URL` |
| `tests/integration/test_hub_reentrancy.py` | Real reentrancy spike |

Tests to add first (`tests/integration/test_hub_reentrancy.py`):

1. fixture exposes a tool named `debug_reentrant_store_result` returning only
   a descriptor;
2. when called through gofr-agent, that tool calls gofr-agent `_store_result`
   before its own response is sent;
3. returned producer output is a descriptor with `kind == "gofr.result_ref"`,
   `version == 1`, a non-empty `result_guid`, and `hub_service == "gofr-agent"`;
4. returned producer output does not contain the raw payload anywhere;
5. five concurrent calls complete within 5 seconds and produce unique GUIDs;
6. missing or invalid `GOFR_FIXTURES_HUB_CALLBACK_TOKEN` causes a structured
   `hub.unauthorised` error surfaced through the producer.

Implementation steps:

1. Implement minimal `ResultDescriptor`, `StoreResultRequest`, and
   `StoreResultResponse` pydantic models using the pinned constants. These are
   the same models Phase 1 will extend; do not invent throwaway shapes.
2. Implement minimal `ResultStore.store(...)` returning a descriptor. Use
   `secrets.token_urlsafe(32)` for `result_guid` and the pinned canonical JSON
   serialization for size measurement. TTL/capacity are enforced even at this
   stage but may use simple defaults.
3. Register `_store_result` as a FastMCP tool in `app/mcp_server/mcp_server.py`.
   First statement is `_guard(auth_service, AGENT_HUB_STORE)`. Second statement
   resolves the principal via `resolve_service_principal`. Reject if missing.
4. Reject store requests where `producer_service` does not match the resolved
   principal. Use `hub.unregistered_service`.
5. Add the fixture spike tool to `docker/mcp_fixtures/serve.py`. It reads
   `GOFR_AGENT_HUB_URL` and `GOFR_FIXTURES_HUB_CALLBACK_TOKEN`, opens a fresh
   MCP streamable HTTP client, calls `_store_result`, and returns only the
   descriptor. Do not call `_store_result` after the fixture tool has returned;
   that does not prove reentrancy.
6. Update `docker/compose.fixtures.yml` so the fixtures service receives
   `GOFR_AGENT_HUB_URL=http://gofr-agent:8090/mcp` and
   `GOFR_FIXTURES_HUB_CALLBACK_TOKEN=dev-fixtures-hub-token`.
7. Do not add a no-op echo callback. The spike must exercise the real store.

Validation commands:

```
./scripts/run_tests.sh tests/integration/test_hub_reentrancy.py -v
./scripts/run_tests.sh -v
```

Phase 0b checkpoint: COMPLETE (validated 2026-05-16)

- `_store_result` is reachable reentrantly from a fixture service.
- Concurrent reentrant stores do not deadlock.
- Producer principal mismatch is rejected.
- Missing/invalid callback token is rejected.
- Full suite passes.
- Evidence: reentrancy coverage is part of the green final suite; see the Checkpoint Log and `tmp/full_suite_final.txt`.

If any checkpoint item fails, stop. Do not proceed to Phase 1.

## Phase 1 - Protocol Models, Tool Schemas, And Error Model

Purpose: make the protocol explicit in code before adding more behaviour.

Files likely touched:

| File | Why |
|------|-----|
| `app/hub/models.py` | Pydantic models for descriptors and hub tool requests/responses |
| `app/hub/errors.py` | Structured hub error codes/helpers |
| `tests/unit/test_hub_models.py` | Schema validation |
| `tests/unit/test_hub_errors.py` | Error mapping |

Tests to add first:

1. `ResultDescriptor` requires `kind`, `version`, `result_guid`, and
   `hub_service`.
2. `ResultDescriptor` accepts advisory fields but does not require them.
3. Invalid `kind` and incompatible `version` are rejected by descriptor
   validation used by consumers.
4. Descriptor serialization never includes `payload`.
5. `StoreResultRequest` requires `protocol_version`, `producer_service`,
   `producer_tool`, `result_type`, `schema_id`, and `payload`.
6. `GetResultRequest` requires `protocol_version`, `result_guid`, and
   `hub_service`.
7. `DescribeResultRequest` follows the same structural requirements as get.
8. `ResultMetadata` contains authoritative fields returned by the hub.
9. Every error code from the spec is represented once and maps to an MCP-safe
   error payload.
10. Error messages do not include payloads, bearer tokens, or raw secrets.

Implementation steps:

1. Reuse the constants pinned in this plan (`gofr.result_ref`, descriptor
   `version` 1, `protocol_version` 1). Keep them in `app/hub/models.py`.
2. Extend Phase 0b's pydantic models to the full spec shape: descriptor,
   metadata, store/get/describe requests, and store/get/describe responses.
3. Keep payload typed as JSON-compatible data. Reject binary/blob payloads in
   v1 by validation or by store serialization.
4. Implement helper methods for structural descriptor validation that consumers
   can call before hub fetch.
5. Define string constants for hub error codes (matching the spec) and a
   helper to build `McpError(ErrorData(...))`. Keep them in `app/hub/errors.py`.
6. Do not perform store mutation or MCP registration work in this phase.

Validation commands:

```
./scripts/run_tests.sh tests/unit/test_hub_models.py tests/unit/test_hub_errors.py -v
./scripts/run_tests.sh -v
```

Phase 1 checkpoint: COMPLETE (validated 2026-05-16)

- Protocol models match the spec schemas.
- Error codes match the spec exactly.
- Descriptors cannot leak payloads.
- Full suite passes.
- Evidence: protocol-model and error coverage remained green in the final suite; see `tmp/full_suite_final.txt`.

## Phase 2 - Result Store

Purpose: build the process-local store behind the hub tools.

Files likely touched:

| File | Why |
|------|-----|
| `app/hub/store.py` | In-process TTL/size-bounded store |
| `tests/unit/test_hub_store.py` | Store behaviour and limits |

Tests to add first:

1. `store()` returns a descriptor with `secrets.token_urlsafe(32)`-shaped GUID
   (43-char URL-safe base64).
2. Two stored results never share a GUID across a large sample.
3. Payload plus authoritative metadata can be fetched by GUID before expiry.
4. Fetch after expiry returns `hub.expired_result`.
5. Unknown GUID returns `hub.unknown_result`.
6. Oversized payload returns `hub.oversized_result`. Size is measured with the
   pinned canonical JSON serialization; the test uses the same helper.
7. Store at max count returns `hub.capacity_exceeded`. Eviction is not allowed
   in v1; prefer rejection.
8. Requested TTL is capped by config.
9. Zero or negative TTL is rejected with `hub.malformed_request`.
10. Authoritative metadata is not affected by mutating advisory descriptor
    fields after store.
11. Tests use an injectable clock (`app.hub.clock.Clock`); do not use
    `time.sleep` or `asyncio.sleep` for time progression.
12. Concurrent store/fetch operations are safe (use `asyncio.gather`).

Implementation steps:

1. Use `secrets.token_urlsafe(32)` for GUIDs. Do not use `uuid4()` or sequential
   ids.
2. Define a single `payload_size_bytes(payload)` helper using the pinned
   canonical JSON serialization, exported for use in store, producer precheck,
   and tests.
3. Store payload and authoritative metadata in an internal record keyed by GUID.
4. Use `asyncio.Lock` since store methods are called from async MCP tools.
5. Define `app/hub/clock.py::Clock` with `monotonic()` and a deterministic test
   double. Inject it into the store.
6. Delete expired entries during get/describe/store and optionally through a
   sweep helper.
7. Return structured hub errors; do not raise raw exceptions past the hub
   boundary.

Validation commands:

```
./scripts/run_tests.sh tests/unit/test_hub_store.py -v
./scripts/run_tests.sh -v
```

Phase 2 checkpoint: COMPLETE (validated 2026-05-16)

- Store limits and TTL are deterministic under test.
- GUIDs are unguessable.
- Metadata is authoritative.
- Full suite passes.
- Evidence: store-limit coverage, including advisory-metadata bounds, passed in `tmp/remediation_slice.txt` and the final suite.

## Phase 3 - Hub MCP Tools, Auth, And Hidden-Tool Filtering

Purpose: expose final hub tools on gofr-agent safely and keep them out of model
reach.

Files likely touched:

| File | Why |
|------|-----|
| `app/mcp_server/mcp_server.py` | Register `_store_result`, `_get_result`, `_describe_result` (extends Phase 0b) |
| `app/agent/tool_factory.py` | Single canonical filter point for reserved protocol tool names; consumed by system prompt |
| `app/agent/system_prompt.py` | Use the filtered tool list from `tool_factory`; do not implement a second filter |
| `app/services/discovery.py` | Carry a `model_visible: bool` flag on `MCPToolInfo` if needed |
| `tests/unit/test_mcp_server_hub_tools.py` | Tool auth, schemas, and error paths |
| `tests/unit/test_system_prompt.py` | Reserved protocol tools hidden |
| `tests/unit/test_tool_factory.py` | Reserved protocol tools hidden, normal underscore tools preserved |

Tests to add first:

1. `_store_result` accepts a valid service callback token and valid request.
2. `_store_result` rejects ordinary `ask` tokens.
3. `_store_result` rejects a callback token mapped to a different
   `producer_service`.
4. `_store_result` rejects an unregistered service.
5. `_store_result` rejects a result type outside the producer's registered
   capabilities.
6. `_get_result` accepts a valid consumer service token, GUID, and expected
   result type/schema.
7. `_get_result` rejects unknown, expired, schema-mismatched, and capability-
   denied requests.
8. `_describe_result` returns metadata only, never payload.
9. Hub tools raise `McpError(ErrorData(...))`, never raw exceptions.
10. Reserved protocol tools are not included in the system prompt.
11. Reserved protocol tools are not converted into pydantic-ai model tools.
12. A non-protocol downstream tool named `_debug_status` remains model-visible
    unless explicitly marked hidden.

Implementation steps:

1. Extend `_store_result` from Phase 0b to enforce result-type capabilities and
   register `_get_result` and `_describe_result` in
   `app/mcp_server/mcp_server.py`.
2. The first statement in each FastMCP hub tool must be `_guard(auth_service,
   REQUIRED_ACTIVITY)`. The existing `_guard` returns the token; pass it to
   `resolve_service_principal` from Phase 0a as the second statement.
3. Enforce registration capability: `can_publish` for store, `can_consume` for
   get/describe.
4. Enforce registered `result_types` on store and get/describe.
5. Convert all hub errors to `McpError(ErrorData(...))` using the helper from
   Phase 1. Never raise raw exceptions across the MCP boundary.
6. Hidden-tool filtering: add a single `RESERVED_PROTOCOL_TOOLS` constant in
   `app/agent/tool_factory.py`. The factory must drop any tool whose name is
   in the set or whose `model_visible` flag is `False`. `system_prompt.py` must
   consume the factory output, not re-filter. Do not use
   `name.startswith("_")`.
7. `list_services` must use `ServiceConfig.safe_dump()` (or equivalent) and
   must never reveal callback tokens or payloads. Add an explicit assertion in
   tests.

Validation commands:

```
./scripts/run_tests.sh tests/unit/test_mcp_server_hub_tools.py tests/unit/test_system_prompt.py tests/unit/test_tool_factory.py -v
./scripts/run_tests.sh -v
```

Phase 3 checkpoint: COMPLETE (validated 2026-05-16)

- Hub tools are protected and schema-validating.
- Model-facing surfaces cannot call hub tools.
- Normal underscore-prefixed tools are not accidentally hidden.
- Full suite passes.
- Evidence: tool filtering/auth coverage remained green in the final suite; grep checks also confirmed no `startswith("_")` blanket hiding remains.

## Phase 4a - Service Discovery And Hub Registration

Purpose: register gofr-agent as a hub with downstream services that advertise
the reserved registration tool.

Files likely touched:

| File | Why |
|------|-----|
| `app/services/discovery.py` | Preserve protocol tool metadata without surfacing it to the model |
| `app/services/registry.py` | Call `_register_results_hub` when present |
| `tests/integration/test_registry_hub_registration.py` | Registration round-trip |

Tests to add first:

1. Service without `_register_results_hub` registers normally.
2. Service with `_register_results_hub` receives the spec-defined request.
3. Registration request contains hub URL, tool names, TTL, payload limits,
   descriptor kind, and protocol version.
4. Registration request does not contain callback tokens or other secrets.
5. Accepted registration records `supports_results_hub`, `can_publish`,
   `can_consume`, and `result_types`.
6. Rejected registration records `registration_error` but does not crash all
   service registration.
7. Incompatible protocol version is rejected and recorded.
8. Registration timeout/failure degrades that service only.

Implementation steps:

1. During tool discovery, propagate `model_visible=False` for the reserved
   `_register_results_hub` tool so it is not surfaced to the model, but keep
   it in `MCPToolInfo` for the registry.
2. Extend `ServiceRegistry._register_one`: after `discover_tools` succeeds, if
   the service exposes `_register_results_hub` and `GOFR_AGENT_HUB_ENABLED` is
   true, call it via the existing pool session using gofr-agent's outbound
   service identity. The existing `_record_success` call must follow, even if
   hub registration fails; in that case set `registration_error` and clear
   `supports_results_hub`.
3. Build the registration request from `GofrAgentConfig` and the reserved hub
   tool names. Do not include callback credentials.
4. Reject incompatible protocol versions and record `registration_error`. Do
   not raise; the service stays usable as a non-hub service.
5. Persist registration capability metadata on the registry entry even on
   rejection (with `supports_results_hub=False`).
6. Keep non-hub service behaviour unchanged.

Validation commands:

```
./scripts/run_tests.sh tests/integration/test_registry_hub_registration.py -v
./scripts/run_tests.sh -v
```

Phase 4a checkpoint: COMPLETE (validated 2026-05-16)

- Hub registration is automatic when the reserved tool is present.
- Non-hub services continue to work.
- Version mismatch and rejection paths are tested.
- Full suite passes.
- Evidence: registration round-trip coverage is part of the final green suite; see `tmp/full_suite_final.txt`.

## Phase 4b - Registry Capability Surfacing

Purpose: make hub capability visible to users/operators without leaking secrets.

Files likely touched:

| File | Why |
|------|-----|
| `app/services/__init__.py` | Hub capability fields on service models if needed |
| `app/services/models.py` | Re-export updated models |
| `app/services/registry.py` | Store capability metadata |
| `app/mcp_server/mcp_server.py` | `list_services` returns capabilities |
| `tests/unit/test_services_models.py` | Capability fields |
| `tests/integration/test_mcp_server_integration.py` | `list_services` shape |

Tests to add first:

1. Registry stores `supports_results_hub`, `can_publish_results`,
   `can_consume_results`, `result_types`, and `registration_error`.
2. `list_services` returns capability metadata for accepted, rejected, and
   non-hub services.
3. `list_services` does not return outbound service tokens, callback tokens,
   payloads, or raw registration secrets.
4. Model-facing tool list excludes reserved protocol tools while service status
   still reports that the service is hub-capable.

Implementation steps:

1. Add capability fields to the smallest appropriate model. Avoid mixing secret
   config fields with public response fields.
2. Keep registry state as the source of truth for capabilities.
3. Update `list_services` response shape and tests together.
4. Preserve backward compatibility for existing `list_services` callers.

Validation commands:

```
./scripts/run_tests.sh tests/unit/test_services_models.py tests/integration/test_mcp_server_integration.py -v
./scripts/run_tests.sh -v
```

Phase 4b checkpoint: COMPLETE (validated 2026-05-16)

- Operators can see hub capability status.
- No secret leaks through service listing.
- Full suite passes.
- Evidence: `list_services` hub capability/no-token assertions remained green in the final suite; see `tmp/full_suite_final.txt`.

## Phase 5 - Fixture Producer Support

Purpose: migrate the first real producer path: OHLCV history publishes bars to
the hub and returns a descriptor.

Files likely touched:

| File | Why |
|------|-----|
| `docker/mcp_fixtures/serve.py` | `_register_results_hub`, callback token config, producer callback |
| `docker/compose.fixtures.yml` | Inject callback token/env if needed |
| `tests/integration/test_instruments_service.py` | OHLCV publishes descriptor |

Tests to add first:

1. Fixture `_register_results_hub` accepts the request shape and returns
   `accepted`, `protocol_version`, `can_publish`, `can_consume`, and
   `result_types`.
2. `instruments.get_ohlcv_history` returns an `ohlcv_bars` descriptor when hub
   registration is active.
3. The producer response does not include raw OHLCV bars.
4. The hub stores authoritative metadata with `result_type = ohlcv_bars`, the
   expected schema id, producer service, producer tool, and payload bytes.
5. Hub-side oversize rejection is tested by forcing a low max-payload setting.
6. Producer-side precheck, if implemented, is only a convenience and does not
   replace the hub oversize test.
7. Missing callback token produces a structured error surfaced by the producer.

Implementation steps:

1. Fixture stores hub registration details received from gofr-agent in process
   memory.
2. Fixture receives callback token through env config. Use the exact env name
   chosen in Phase 0.
3. `get_ohlcv_history` keeps its existing data generation/query behaviour.
4. After producing bars, call gofr-agent `_store_result` with the final schema:
   protocol version, producer service, producer tool, result type, schema id,
   payload, summary, source args, optional TTL.
5. Return only the descriptor to gofr-agent/model.
6. Preserve non-hub fallback only if needed for compatibility. Prefer descriptor
   path whenever registration is active.

Validation commands:

```
./scripts/run_tests.sh tests/integration/test_instruments_service.py tests/integration/test_hub_reentrancy.py -v
./scripts/run_tests.sh -v
```

Phase 5 checkpoint: COMPLETE (validated 2026-05-16)

- OHLCV producer returns descriptor only.
- Hub owns the payload and authoritative metadata.
- Oversize and missing-token paths are tested.
- Full suite passes.
- Evidence: producer descriptor coverage remained green in the final suite; the manual smoke run also showed descriptor-only producer output in `tmp/fixture_chat_final.txt`.

## Phase 6 - Fixture Consumer Support

Purpose: migrate analytics consumers to fetch bars from the hub by descriptor.

Files likely touched:

| File | Why |
|------|-----|
| `docker/mcp_fixtures/serve.py` | Analytics tools accept `bars_ref` |
| `tests/integration/test_analytics_service.py` | Descriptor consumption |

Tests to add first:

1. `simple_return`, `historical_volatility`, and `max_drawdown` accept
   `bars_ref`.
2. Each consumer validates descriptor structural fields before calling the hub.
3. Each consumer calls `_get_result` with `expected_result_type = ohlcv_bars`
   and the expected schema id.
4. Each consumer computes the same values from descriptor-fetched bars as it did
   from inline bars.
5. Tampered advisory descriptor fields do not change behaviour. Same GUID with
   modified `result_type`, `schema_id`, or `producer_service` must use hub
   metadata instead.
6. Malformed `kind` or `version` is rejected before hub fetch.
7. Unknown/expired GUID errors surface cleanly.
8. Consumer result-type capability denial is tested.

Implementation steps:

1. Add `bars_ref: ResultDescriptor` to analytics tool schemas.
2. If keeping inline `bars` during migration, make `bars_ref` the preferred path
   in schema descriptions and prompts.
3. Implement a shared fixture helper for descriptor structural validation and
   hub fetch to avoid three divergent implementations.
4. The helper must pass expected type/schema to `_get_result` and trust the
   returned metadata.
5. Validate fetched payload shape before computing analytics.
6. Do not read advisory descriptor `result_type`/`schema_id` as authority.

Validation commands:

```
./scripts/run_tests.sh tests/integration/test_analytics_service.py tests/integration/test_hub_negative_paths.py -v
./scripts/run_tests.sh -v
```

Phase 6 checkpoint: COMPLETE (validated 2026-05-16)

- Analytics tools work from descriptors.
- Tampering advisory fields does not affect trust decisions.
- Full suite passes.
- Evidence: analytics descriptor-consumer and negative-path coverage remained green in the final suite; see `tmp/full_suite_final.txt`.

## Phase 7 - Agent Orchestration Contract Update

Purpose: make the agent reliably pass descriptors between tools and stop using
the scratchpad for descriptor-enabled workflows.

Files likely touched:

| File | Why |
|------|-----|
| `app/agent/tool_factory.py` | Descriptor passthrough and no scratchpad substitution for descriptor-enabled tools |
| `app/agent/system_prompt.py` | Descriptor handoff instructions |
| `app/agent/deps.py` | Track descriptor metadata only for descriptor-enabled workflows |
| `tests/unit/test_tool_factory.py` | Descriptor passthrough and ModelRetry |
| `tests/unit/test_system_prompt.py` | Prompt covers descriptors |
| `tests/unit/test_agent.py` | Agent-level descriptor handoff |

Tests to add first:

1. Tool wrapper passes descriptor objects through without expanding payloads.
2. Descriptor-enabled analytics tool missing `bars_ref` triggers `ModelRetry`
   with a concise corrective message that names the missing argument.
3. Wrapper does not auto-substitute inline bars from `AgentDeps.artifacts` for
   any argument whose JSON schema has
   `"x-gofr-result-descriptor": true`.
4. Legacy non-descriptor required args still receive scratchpad enrichment via
   `_enrich_missing_args` (regression for current behaviour in
   `app/agent/tool_factory.py`).
5. System prompt tells the model to forward descriptors verbatim and not expand
   payloads.
6. System prompt does not list reserved hub protocol tools.
7. Descriptor `summary` is wrapped in `_TOOL_DATA_START`/`_TOOL_DATA_END`
   sentinels (the existing convention in `app/agent/tool_factory.py`).
8. For descriptor-enabled tool calls, `EventCollector` payload size is at or
   below `tool_result_max_chars` and does not include any list value longer
   than 32 elements.

Implementation steps:

1. In `_enrich_missing_args` (or a wrapper around it), skip enrichment for any
   required argument whose property schema has `"x-gofr-result-descriptor":
   true`.
2. If a required descriptor argument is still missing after the model's call,
   raise `ModelRetry(f"Tool {tool_name} requires descriptor argument
   {arg_name}; pass it directly from the previous tool's response.")`. Do not
   silently substitute full payloads.
3. Keep descriptor metadata in `AgentDeps` only for traceability and retry
   hints, not as a hidden payload cache.
4. Update prompt text in a small, targeted way: a one-paragraph rule that says
   "forward descriptors verbatim".
5. Preserve existing tests for inline tools and legacy scratchpad behaviour.

Validation commands:

```
./scripts/run_tests.sh tests/unit/test_tool_factory.py tests/unit/test_system_prompt.py tests/unit/test_agent.py -v
./scripts/run_tests.sh -v
```

Phase 7 checkpoint: COMPLETE (validated 2026-05-16)

- The model is guided to pass descriptors, not payloads.
- Descriptor-enabled tools no longer get hidden payload substitution.
- Full suite passes.
- Evidence: descriptor passthrough/system-prompt coverage remained green in the final suite; see `tmp/full_suite_final.txt`.

## Phase 8 - End-to-end Workflow Validation And Negative Paths

Purpose: prove the whole workflow and all agreed failure modes.

Files likely touched:

| File | Why |
|------|-----|
| `tests/integration/test_agent_integration.py` | Hub workflow |
| `tests/integration/test_hub_negative_paths.py` | Failure modes |
| `scripts/fixture_chat.py` | Optional readability/debug output tweaks |

Positive test to add:

1. AAPL OHLCV-to-analytics workflow completes with descriptors only; raw bars
   never appear in model context, final answer, event payloads, or logs.

Negative tests to add:

1. Concurrent producer callbacks to real `_store_result` during long-running
   fixture tool calls.
2. Hub `_store_result` oversize rejection returns `hub.oversized_result`.
3. Hub `_store_result` missing/invalid callback auth returns `hub.unauthorised`.
4. Hub `_store_result` token principal mismatch returns
   `hub.unregistered_service` or a clearer equivalent documented in spec.
5. Hub `_store_result` producer result-type denial returns
   `hub.result_type_not_allowed`.
6. Consumer `_get_result` unknown GUID returns `hub.unknown_result`.
7. Consumer `_get_result` expired GUID returns `hub.expired_result`.
8. Consumer `_get_result` consumer result-type denial returns
   `hub.result_type_not_allowed`.
9. Model-tampered descriptor advisory fields do not alter trust decisions.
10. Malformed structural descriptor fields reject before hub fetch.
11. Prompt-injection-style summary is sentinel-wrapped and does not alter agent
    behaviour.
12. Non-protocol `_`-prefixed downstream tool remains model-visible when not
    marked hidden.
13. `list_services` never leaks callback tokens.
14. Full AAPL fixture chat command succeeds in descriptor mode.

Implementation steps:

1. Add tests as integration tests first. Keep fixtures deterministic.
2. Use the same date/ticker workflow already used during manual validation:
   AAPL, 2026-04-01 to 2026-05-13.
3. Concrete context-leak check: for every `EventCollector` event captured
   during the AAPL run, assert (a) no event payload contains a JSON array
   longer than 32 entries, and (b) no event payload contains the literal
   strings `"open"`, `"high"`, `"low"`, `"close"` together. The descriptor
   `summary` is exempt because it is bounded.
4. Keep failure assertions on structured error codes where possible.
5. Run the manual fixture chat command after automated tests pass. This is a
   developer post-step and is not gated by CI; it requires `OPENROUTER_API_KEY`
   or another live model.

Validation commands:

```
./scripts/run_tests.sh tests/integration/test_agent_integration.py tests/integration/test_hub_negative_paths.py -v
./scripts/run_tests.sh -v
```

Developer post-step (not CI-gated):

```
uv run python scripts/fixture_chat.py --model fixture-descriptor-smoke --verbose --once "Using downstream tools only, calculate AAPL simple return, 30-day historical volatility, and max drawdown from 2026-04-01 to 2026-05-13."
```

Phase 8 checkpoint: COMPLETE (validated 2026-05-16)

- End-to-end descriptor workflow works.
- Negative paths prove the design boundaries.
- No large payload reaches model context.
- Full suite and fixture chat pass.
- Evidence: `tmp/fixture_chat_final.txt` shows `_store_result`, descriptor-only producer output, analytics `bars_ref` handoff, and `_get_result` fetches; `tmp/full_suite_final.txt` is green.

## Post-Implementation Review Remediation Gate

Purpose: resolve issues found during implementation review before marking the
plan complete against the spec. These items gate Phase 9 and final acceptance.

Required fixes:

1. Move registry/pool shutdown cancellation handling into production code.
   Tests must not hide `asyncio.CancelledError` from `registry.shutdown()` or
   `pool.stop()` with broad teardown-only suppression. `SessionPool.stop()` or
   `ServiceRegistry.shutdown()` must close all available slots, clear registry
   state, and tolerate MCP transport cancellation during normal shutdown.
2. Keep `./scripts/run_tests.sh` target handling correct for both filesystem
   paths and pytest node IDs. A command such as
   `./scripts/run_tests.sh tests/unit/test_pool.py::TestSessionPoolStart::test_is_healthy_false_before_start -q`
   must run the requested target, not the full unit and integration suites.
3. Enforce hub memory bounds for stored metadata as well as payloads. The hub
   currently sizes only `payload`; bounded fields such as `summary` and
   `source_args` must either have explicit limits or be included in a total
   stored-record size check so publishers cannot bypass `hub_max_payload_bytes`
   with oversized advisory metadata.
4. Correct the descriptor workflow test so its deterministic model matches the
   user request. If the prompt asks for 30-day historical volatility, the test
   model must call the analytics tool with `window=30`, and assertions must
   verify the window-sensitive result rather than only checking that volatility
   is non-null.

Tests/checks to add or update:

1. Unit coverage proving `SessionPool.stop()` and/or `ServiceRegistry.shutdown()`
   handles transport `asyncio.CancelledError` without leaking it to callers and
   still clears internal state.
2. Runner coverage or a documented manual check proving pytest node IDs remain
   targeted after the import-mode fix.
3. Hub store tests proving oversized `summary` / `source_args` are rejected or
   counted toward the configured limit, and that accepted descriptors remain
   bounded and payload-free.
4. End-to-end descriptor workflow assertions proving the requested analytics
   window is the one actually used.

Validation commands:

```
./scripts/run_tests.sh tests/unit/test_pool.py tests/unit/test_registry.py tests/unit/test_hub_store.py tests/integration/test_agent_integration.py -v
./scripts/run_tests.sh tests/unit/test_pool.py::TestSessionPoolStart::test_is_healthy_false_before_start -q
./scripts/run_tests.sh -v
```

Review remediation checkpoint: COMPLETE (validated 2026-05-16)

- Shutdown robustness is implemented in production code, not only test cleanup.
- Targeted test invocations stay targeted for file paths and pytest node IDs.
- Hub storage limits cover payload and advisory metadata.
- The AAPL descriptor workflow test matches the requested 30-day calculation.
- Full suite passes after the remediations.
- Evidence: `tmp/remediation_slice.txt`, `tmp/nodeid_after_fix.txt`, and the final `tmp/full_suite_final.txt` run all passed.

## Phase 9 - Documentation And Cleanup

Purpose: make the implementation maintainable and remove temporary spike code.

Files likely touched:

| File | Why |
|------|-----|
| `README.md` | Brief mention of hub mode |
| `docs/SPEC.md` | Update inline-result references |
| `docs/react_integration_guide.md` | Note descriptors are not user-facing payloads |
| `services.yml.example` | Hub-capable service example and callback token env |
| `docs/mcp_artifact_handoff_spec.md` | Final wording updates if implementation changed approved details |
| `docs/mcp_artifact_handoff_implementation_plan.md` | Mark checkpoints complete |

Tests/checks to run:

1. Search for stale terms and rejected patterns.
2. Confirm no temporary no-op spike code remains.
3. Confirm docs do not instruct users to use `localhost` for MCP service-to-
   service calls.
4. Confirm examples use env vars for callback tokens, not inline secrets.

Implementation steps:

1. Update user-facing docs with hub config, callback credential provisioning,
   descriptor model, and reserved protocol tool names.
2. Update `services.yml.example` with a hub-capable service example using
   Docker service names and `hub_callback_token_env`.
3. Remove or rename any debug-only fixture tools that should not remain. If a
   debug tool remains, mark it clearly and keep it out of production manifests.
4. Remove temporary comments or TODOs added during the spike unless they point
   to real future work.
5. Run grep checks before final validation.

Suggested grep checks (review hits, do not blanket-reject):

```
rg -n 'url:\s*http://(localhost|127\.0\.0\.1)' services.yml.example docker docs
rg -n 'startswith\(\"_\"\)' app tests
rg -n 'no-op|echo callback' app tests docker docs
rg -n '^\s*print\(' app docker/mcp_fixtures
rg -n 'hub_callback_token|GOFR_FIXTURES_HUB_CALLBACK_TOKEN|GOFR_AGENT_HUB_' app tests docker docs services.yml.example
```

Validation commands:

```
./scripts/run_tests.sh --quality
./scripts/run_tests.sh -v
```

Phase 9 checkpoint: COMPLETE (validated 2026-05-16)

- Docs and examples match the final implementation.
- No temporary spike-only behaviour remains.
- Full suite passes.
- Evidence: grep checks were clean, `./scripts/run_tests.sh --quality` passed into `tmp/quality_final.txt`, and the final suite passed into `tmp/full_suite_final.txt`.

## Final Acceptance Checklist

Final acceptance status: COMPLETE (validated 2026-05-16).

Before reporting completion, verify all of the following:

1. `git --no-pager status --short` shows only intentional files changed.
2. Every phase checkpoint in this file is marked complete with evidence.
3. Full test suite passes through `./scripts/run_tests.sh -v`.
4. Manual fixture chat command passes in descriptor mode.
5. `list_services` shows hub capabilities but no tokens.
6. Model-facing tool list excludes only reserved protocol tools, not all
   underscore-prefixed tools.
7. Raw OHLCV bars do not appear in model context for the AAPL workflow.
8. Unknown, expired, oversized, unauthorised, result-type-denied, and tampered
   descriptor paths all have tests.
9. No code uses `print()` or stdlib `logging`; use `StructuredLogger` patterns.
10. No docs or examples require `localhost` for service-to-service MCP traffic.

## Stop Conditions

Stop and ask before proceeding if any of these happen:

1. Real `_store_result` reentrancy cannot be proven.
2. Callback token-to-service mapping cannot be implemented without changing the
   auth architecture more broadly than this plan allows.
3. A phase requires distributed/shared storage.
4. A test can only be made to pass by exposing payloads to the model.
5. A test can only be made to pass by hiding all underscore-prefixed tools.
6. A phase requires sending callback tokens in registration payloads.
7. Full suite failures indicate unrelated breakage that would require broad
   refactoring outside this feature.

When stopping under any of these, follow `A3` from `copilot-instructions.md`:
write a short `docs/mcp_results_hub_<phase>_strategy.md` capturing the symptom,
hypothesised cause, and the smallest experiment that would resolve the
uncertainty, then ask the user before changing the spec or this plan.
