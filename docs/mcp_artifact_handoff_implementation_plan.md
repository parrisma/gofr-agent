# MCP Results Hub Implementation Plan

Status: DRAFT v4 - explicit implementation runbook
Spec: `docs/mcp_artifact_handoff_spec.md`

## Read This First

This plan is intentionally detailed. Follow it in order. Do not jump ahead,
combine phases, or simplify the design to make a local test pass.

All commands run from the repository root. Use `uv` and `./scripts/run_tests.sh`
only. Do not run raw `pytest`, do not use `pip`, and do not use `localhost` or
`127.0.0.1` for service-to-service URLs.

Do not `git add`, `commit`, or `push` unless explicitly asked.

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
./scripts/run_tests.sh -k "<phase-specific selector>" -v
./scripts/run_tests.sh -k code_quality -v
./scripts/run_tests.sh -v
```

If the full suite fails, do not proceed to the next phase. Diagnose the failure.
If it is clearly unrelated and cannot be safely fixed within the phase, stop and
ask before widening scope.

## Checkpoint Log

Update this table during implementation. Do not mark a phase done until its
full validation set passes.

| Phase | Status | Required Evidence |
|-------|--------|-------------------|
| 0 | TODO | Real `_store_result` reentrancy passes, config/auth mapping proven, full suite passes |
| 1 | TODO | Models/errors tests pass, full suite passes |
| 2 | TODO | Store tests pass, full suite passes |
| 3 | TODO | Hub MCP tool tests and hidden-tool tests pass, full suite passes |
| 4a | TODO | Registration tests pass, full suite passes |
| 4b | TODO | Capability surfacing tests pass, full suite passes |
| 5 | TODO | Fixture producer tests pass, full suite passes |
| 6 | TODO | Fixture consumer tests pass, full suite passes |
| 7 | TODO | Agent orchestration tests pass, full suite passes |
| 8 | TODO | Positive and negative end-to-end tests pass, full suite passes |
| 9 | TODO | Docs/example validation and full suite pass |

## Phase 0 - Real Reentrancy Spike, Config, And Credential Decisions

Purpose: prove the hardest runtime assumption before building the rest. A
fixture service must call the real `_store_result` path while gofr-agent is
still waiting for that fixture tool response.

Files likely touched:

| File | Why |
|------|-----|
| `app/config.py` | Hub config fields and URL validation |
| `app/auth/permissions.py` | Hub activity constants |
| `app/auth/_dev_auth_service.py` | Dev token with hub activities |
| `app/services/__init__.py` | `hub_callback_token` / `hub_callback_token_env` on `ServiceConfig` |
| `app/mcp_server/mcp_server.py` | Minimal final-shaped `_store_result` hub tool |
| `app/hub/__init__.py` | New package if needed for spike code |
| `app/hub/models.py` | Minimal final-shaped store request/descriptor models |
| `app/hub/store.py` | Minimal final-shaped in-process store |
| `docker/mcp_fixtures/serve.py` | Reentrant producer spike tool |
| `docker/compose.fixtures.yml` | Inject fixture callback token if needed |
| `tests/unit/test_config.py` | Hub config validation |
| `tests/unit/test_auth_permissions.py` | Hub activity constants |
| `tests/unit/test_services_models.py` | Callback token env resolution and non-leakage |
| `tests/integration/test_hub_reentrancy.py` | Real reentrancy spike |

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
   - `GoFRAgentHubStore`, `GoFRAgentHubFetch`, and optional
     `GoFRAgentHubRegister` constants exist;
   - hub activities are included in `ALL_ACTIVITIES` only if this repo's auth
     conventions require that list to enumerate all known activities;
   - ordinary read/ask dev tokens do not grant hub activities.
3. `tests/unit/test_services_models.py`
   - `hub_callback_token_env` resolves from env like `token_env`;
   - explicit `hub_callback_token` takes precedence over env;
   - missing callback token is allowed for non-hub services;
   - model dump/list-services helper does not expose callback token values.
4. `tests/integration/test_hub_reentrancy.py`
   - fixture exposes a tool such as `debug_reentrant_store_result`;
   - when called through gofr-agent, that tool calls gofr-agent `_store_result`
     before returning;
   - returned producer output contains a descriptor with `kind`, `version`,
     `result_guid`, and `hub_service`;
   - returned producer output does not contain the raw payload;
   - five concurrent calls complete within a bounded timeout and produce unique
     GUIDs;
   - missing/invalid callback token is rejected with a structured error.

Implementation steps:

1. Add config fields to `GofrAgentConfig`: `hub_enabled`, `hub_url`,
   `hub_default_ttl_seconds`, `hub_max_payload_bytes`, `hub_max_results`,
   `hub_protocol_version`.
2. Validate config in `GofrAgentConfig.from_env()` or pydantic validators.
   Reject local-only hub URLs when hub is enabled.
3. Add hub permission constants in `app/auth/permissions.py`:
   `AGENT_HUB_STORE = "GoFRAgentHubStore"`,
   `AGENT_HUB_FETCH = "GoFRAgentHubFetch"`, and optionally
   `AGENT_HUB_REGISTER = "GoFRAgentHubRegister"`.
4. Update `DevAuthService` with a dedicated fixture callback token, for
   example `dev-hub-token`, that grants only the hub activities needed for the
   spike. Do not grant hub activities to `dev-read-token`.
5. Extend `ServiceConfig` with optional `hub_callback_token` and
   `hub_callback_token_env`. Resolve env values in the existing model validator.
   Never include these fields in `list_services` responses or logs.
6. Implement token-to-service lookup using configured callback tokens. Use
   `secrets.compare_digest()` or a hashed lookup. Never log token values.
7. Implement a minimal final-shaped `ResultStore` and `_store_result` path.
   It may be small in Phase 0, but it must use the final names and final
   request/response shape so later phases extend it instead of replacing it.
8. `_store_result` must do real work: auth guard, token-to-service check,
   payload-size check, store mutation under a lock, descriptor creation, and
   structured error on failure.
9. Fixture spike tool reads `GOFR_AGENT_HUB_URL` and its callback token env,
   opens a fresh MCP streamable HTTP client to gofr-agent, calls
   `_store_result`, receives the descriptor, and returns only that descriptor.
10. Do not add a no-op echo callback. Do not call `_store_result` after the
    fixture tool has returned; that does not prove reentrancy.

Validation commands:

```
./scripts/run_tests.sh -k "test_config or test_auth_permissions or test_services_models" -v
./scripts/run_tests.sh -k hub_reentrancy -v
./scripts/run_tests.sh -k code_quality -v
./scripts/run_tests.sh -v
```

Phase 0 checkpoint:

- `_store_result` is reachable reentrantly from a fixture service.
- Concurrent reentrant stores do not deadlock.
- Callback token mapping proves the caller is the registered service.
- Local-only hub URLs are rejected.
- Full suite passes.

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

1. Define constants for descriptor kind, descriptor version, and protocol
   version. Keep them in one module.
2. Define pydantic models for descriptor, metadata, store/get/describe
   requests, and store/get/describe responses.
3. Keep payload typed as JSON-compatible data. Reject binary/blob payloads in
   v1 by validation or by store serialization.
4. Implement helper methods for structural descriptor validation that consumers
   can call before hub fetch.
5. Define a small `HubErrorCode` enum or string constants and a helper to build
   `McpError(ErrorData(...))` later.
6. Do not perform store mutation or MCP registration work in this phase.

Validation commands:

```
./scripts/run_tests.sh -k "hub_models or hub_errors" -v
./scripts/run_tests.sh -k code_quality -v
./scripts/run_tests.sh -v
```

Phase 1 checkpoint:

- Protocol models match the spec schemas.
- Error codes match the spec exactly.
- Descriptors cannot leak payloads.
- Full suite passes.

## Phase 2 - Result Store

Purpose: build the process-local store behind the hub tools.

Files likely touched:

| File | Why |
|------|-----|
| `app/hub/store.py` | In-process TTL/size-bounded store |
| `tests/unit/test_hub_store.py` | Store behaviour and limits |

Tests to add first:

1. `store()` returns a descriptor with a cryptographically random GUID.
2. Two stored results never share a GUID across a large sample.
3. Payload plus authoritative metadata can be fetched by GUID before expiry.
4. Fetch after expiry returns `hub.expired_result`.
5. Unknown GUID returns `hub.unknown_result`.
6. Oversized payload returns `hub.oversized_result`.
7. Store at max count returns `hub.capacity_exceeded` or evicts only if the
   spec is updated to allow eviction. Prefer rejection for v1.
8. Requested TTL is capped by config.
9. Zero or negative TTL is rejected.
10. Authoritative metadata is not affected by mutating advisory descriptor
    fields after store.
11. Tests use an injectable clock; do not use real sleeps.
12. Concurrent store/fetch operations are safe.

Implementation steps:

1. Use `secrets.token_urlsafe(32)` or an equivalent cryptographic random source
   for GUIDs. Do not use sequential IDs or predictable hashes.
2. Use canonical JSON serialization to measure payload bytes. Use the same
   measurement in tests and implementation.
3. Store payload and authoritative metadata in an internal record keyed by GUID.
4. Use an `asyncio.Lock` or equivalent if store methods are called from async
   MCP tools.
5. Delete expired entries during get/describe/store and optionally through a
   sweep helper.
6. Return structured hub errors; do not raise raw exceptions past the hub
   boundary.

Validation commands:

```
./scripts/run_tests.sh -k hub_store -v
./scripts/run_tests.sh -k code_quality -v
./scripts/run_tests.sh -v
```

Phase 2 checkpoint:

- Store limits and TTL are deterministic under test.
- GUIDs are unguessable.
- Metadata is authoritative.
- Full suite passes.

## Phase 3 - Hub MCP Tools, Auth, And Hidden-Tool Filtering

Purpose: expose final hub tools on gofr-agent safely and keep them out of model
reach.

Files likely touched:

| File | Why |
|------|-----|
| `app/mcp_server/mcp_server.py` | Register `_store_result`, `_get_result`, `_describe_result` |
| `app/agent/system_prompt.py` | Exclude reserved protocol tools from prompt |
| `app/agent/tool_factory.py` | Exclude reserved protocol tools from model tool surface |
| `app/services/discovery.py` | Add/propagate `model_visible` if needed |
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

1. Register `_store_result`, `_get_result`, and `_describe_result` in
   `app/mcp_server/mcp_server.py`.
2. The first statement in each FastMCP hub tool must be `_guard(auth_service,
   REQUIRED_ACTIVITY)`, per the repository MCP tool pattern.
3. After guard, extract the bearer token through existing request/auth context.
   If no helper exists, add one small helper near existing auth extraction.
4. Map the callback token to a registered service using the Phase 0 explicit
   callback-token mapping.
5. Enforce registration capability: `can_publish` for store, `can_consume` for
   get/describe.
6. Enforce registered `result_types` on store and get/describe.
7. Convert all hub errors to `McpError(ErrorData(...))`.
8. Add exact-name filtering for reserved protocol tool names, or add
   `model_visible = false` and filter on that flag. Do not use a blanket
   `name.startswith("_")` rule.
9. Make sure `list_services` may show capability metadata but never reveals
   callback tokens or payloads.

Validation commands:

```
./scripts/run_tests.sh -k "mcp_server_hub_tools or system_prompt or tool_factory" -v
./scripts/run_tests.sh -k code_quality -v
./scripts/run_tests.sh -v
```

Phase 3 checkpoint:

- Hub tools are protected and schema-validating.
- Model-facing surfaces cannot call hub tools.
- Normal underscore-prefixed tools are not accidentally hidden.
- Full suite passes.

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

1. During tool discovery, keep enough metadata to know `_register_results_hub`
   exists, but do not expose it to the model.
2. After discovery and before marking registration complete, call
   `_register_results_hub` using gofr-agent's existing outbound service
   identity.
3. Build the registration request from `GofrAgentConfig` and the reserved hub
   tool names.
4. Do not include callback credentials in the registration request.
5. Store registration response and errors in service registry state.
6. Keep non-hub service behaviour unchanged.

Validation commands:

```
./scripts/run_tests.sh -k registry_hub_registration -v
./scripts/run_tests.sh -k code_quality -v
./scripts/run_tests.sh -v
```

Phase 4a checkpoint:

- Hub registration is automatic when the reserved tool is present.
- Non-hub services continue to work.
- Version mismatch and rejection paths are tested.
- Full suite passes.

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
./scripts/run_tests.sh -k "services_models or mcp_server_integration" -v
./scripts/run_tests.sh -k code_quality -v
./scripts/run_tests.sh -v
```

Phase 4b checkpoint:

- Operators can see hub capability status.
- No secret leaks through service listing.
- Full suite passes.

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
./scripts/run_tests.sh -k instruments_service -v
./scripts/run_tests.sh -k hub_reentrancy -v
./scripts/run_tests.sh -k code_quality -v
./scripts/run_tests.sh -v
```

Phase 5 checkpoint:

- OHLCV producer returns descriptor only.
- Hub owns the payload and authoritative metadata.
- Oversize and missing-token paths are tested.
- Full suite passes.

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
./scripts/run_tests.sh -k analytics_service -v
./scripts/run_tests.sh -k hub_negative_paths -v
./scripts/run_tests.sh -k code_quality -v
./scripts/run_tests.sh -v
```

Phase 6 checkpoint:

- Analytics tools work from descriptors.
- Tampering advisory fields does not affect trust decisions.
- Full suite passes.

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
   with a concise corrective message.
3. Wrapper does not auto-substitute inline bars from `AgentDeps` scratchpad for
   descriptor-enabled tools.
4. Legacy non-descriptor workflows can still use the scratchpad fallback.
5. System prompt tells the model to forward descriptors verbatim and not expand
   payloads.
6. System prompt does not list reserved hub protocol tools.
7. Descriptor summary is wrapped in the same sentinel convention as tool output.
8. Event/log payload truncation does not expose full bars arrays.

Implementation steps:

1. Detect descriptor-enabled tools from their schemas or registry metadata.
2. For descriptor-enabled required arguments, prefer explicit descriptor passing.
3. If the model omits a required descriptor, raise `ModelRetry`; do not silently
   substitute full payloads.
4. Keep descriptor metadata in `AgentDeps` only for traceability and retry
   hints, not as a hidden payload cache.
5. Update prompt text in a small, targeted way.
6. Preserve existing tests for inline tools and legacy scratchpad behaviour.

Validation commands:

```
./scripts/run_tests.sh -k "tool_factory or system_prompt or test_agent" -v
./scripts/run_tests.sh -k code_quality -v
./scripts/run_tests.sh -v
```

Phase 7 checkpoint:

- The model is guided to pass descriptors, not payloads.
- Descriptor-enabled tools no longer get hidden payload substitution.
- Full suite passes.

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
3. For context-leak checks, assert absence of representative OHLCV array keys or
   payload-size markers in model-facing events, not just final text.
4. Keep failure assertions on structured error codes where possible.
5. Run the manual fixture chat command after automated tests pass.

Validation commands:

```
./scripts/run_tests.sh -k "agent_integration or hub_negative_paths" -v
./scripts/run_tests.sh -k code_quality -v
./scripts/run_tests.sh -v
uv run python scripts/fixture_chat.py --verbose --max-steps 40 --once "Using downstream tools only, calculate AAPL simple return, 30-day historical volatility, and max drawdown from 2026-04-01 to 2026-05-13. If an analytics tool requires bars, fetch OHLCV history first. Return compact JSON with ticker, from_date, to_date, simple_return, annualised_vol, max_drawdown_pct."
```

Phase 8 checkpoint:

- End-to-end descriptor workflow works.
- Negative paths prove the design boundaries.
- No large payload reaches model context.
- Full suite and fixture chat pass.

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

Suggested grep checks:

```
rg "localhost|127\.0\.0\.1|no-op|echo callback|startswith\(\"_\"\)|print\(" app tests docker docs services.yml.example
rg "hub_callback_token|GOFR_FIXTURE|GOFR_AGENT_HUB" app tests docker docs services.yml.example
```

Validation commands:

```
./scripts/run_tests.sh -k code_quality -v
./scripts/run_tests.sh -v
```

Phase 9 checkpoint:

- Docs and examples match the final implementation.
- No temporary spike-only behaviour remains.
- Full suite passes.

## Final Acceptance Checklist

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
