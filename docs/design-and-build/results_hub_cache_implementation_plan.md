# Results Hub Cache Implementation Plan

Status: DRAFT - requires user approval before implementation.
Date: 2026-05-19.
Source: [results_hub_cache_design.md](results_hub_cache_design.md).

## Goal

Implement a session-scoped results hub store behind a generic `external_cache`
backend, using Valkey as the first adapter, without changing the public
descriptor shape and without leaking raw session identifiers into cache keys,
logs, or model-visible payloads.

The implementation must stay incremental. Each stage should land with focused
validation before moving to the next stage.

No implementation should start until this plan is approved.

## Non-goals

- Agent memory or durable long-term storage.
- Valkey replication, Sentinel, clustering, or other multi-node topologies.
- UI feature work beyond the plumbing needed to validate the real-server hub.
- Broad refactors unrelated to hub storage, scope propagation, or health.

## Delivery rules

1. Land the work in the order below. Do not skip ahead.
2. Before each test gate, run `uv run ruff check` on touched Python files.
   Validate touched shell scripts with `bash -n`.
3. After each step, run the targeted `./scripts/run_tests.sh -k ... -v` gate for
   that step and stop if it fails.
4. Only run the full suite after all steps are complete.
5. If test output is too large, redirect it to `tmp/results_hub_cache_<step>.txt`
   and inspect the tail instead of rerunning blindly.

## Current implementation seams

The current implementation is concentrated in these files and should be evolved,
not replaced wholesale:

- [app/hub/store.py](../app/hub/store.py): current in-memory `ResultStore`
- [app/hub/models.py](../app/hub/models.py): protocol models and descriptor shape
- [app/hub/auth.py](../app/hub/auth.py): current static callback-token principal resolution
- [app/mcp_server/mcp_server.py](../app/mcp_server/mcp_server.py): `_store_result`, `_get_result`, `_describe_result`
- [app/services/pool.py](../app/services/pool.py): one-shot downstream session creation and outbound headers
- [app/main_mcp.py](../app/main_mcp.py): startup wiring and health/logging entrypoint
- [tests/unit/test_hub_store.py](../tests/unit/test_hub_store.py): current store behavior
- [tests/unit/test_mcp_server_hub_tools.py](../tests/unit/test_mcp_server_hub_tools.py): current hub tool auth and negative paths
- [tests/integration/test_analytics_hub_integration.py](../tests/integration/test_analytics_hub_integration.py): producer/consumer descriptor flow
- [tests/fixtures/mcp_services/_results_hub.py](../tests/fixtures/mcp_services/_results_hub.py): fixture-side hub callback helper

## Step 0 - Freeze the baseline

Files:

- No production-file changes required at the start.
- Add small characterization tests only if a critical current behavior is not
  already covered.

Work:

1. Run the existing hub-focused unit and integration tests before making any
   behavior changes.
2. Confirm the current descriptor shape is explicitly covered in tests so later
   refactors cannot accidentally add session fields.
3. Confirm the current negative-path tests around expired, unknown, and schema
   mismatch behavior are green before the refactor begins.

Test gate:

```bash
uv run ruff check tests/unit/test_hub_models.py tests/unit/test_hub_store.py tests/unit/test_mcp_server_hub_tools.py tests/integration/test_hub_negative_paths.py tests/integration/test_analytics_hub_integration.py tests/integration/test_registry_hub_registration.py
./scripts/run_tests.sh -k "hub_models or hub_store or mcp_server_hub_tools or hub_negative_paths or analytics_hub_integration or registry_hub_registration" -v
```

Exit criteria:

- Current hub tests pass unchanged.
- Descriptor shape is covered by tests before storage internals change.

## Step 1 - Add generic hub abstractions and config with no behavior change

Files:

- [app/config.py](../app/config.py)
- [app/hub/models.py](../app/hub/models.py) and/or a focused sibling hub types module
- New [app/hub/store_factory.py](../app/hub/store_factory.py)
- [app/hub/__init__.py](../app/hub/__init__.py)
- [tests/unit/test_config.py](../tests/unit/test_config.py)
- New `tests/unit/test_hub_store_factory.py`

Work:

1. Add generic config fields for:
   - `GOFR_AGENT_HUB_STORE_BACKEND`
   - `GOFR_AGENT_HUB_CACHE_URL`
   - cache timeouts/retry budgets
   - cache memory budget
   - active-session budget
   - callback-token TTL
2. Add generic hub types:
   - `HubAccessScope`
   - `HubStoreHealth`
   - `HubResultStore` protocol
3. Add `create_result_store(config)` that returns the existing in-memory store
   by default.
4. Update imports and type hints to depend on the protocol/factory boundary,
   without changing runtime behavior yet.

Test gate:

```bash
uv run ruff check app/config.py app/hub tests/unit/test_config.py tests/unit/test_hub_models.py tests/unit/test_hub_store_factory.py
./scripts/run_tests.sh -k "test_config or hub_models or hub_store_factory" -v
```

Exit criteria:

- Default startup still uses the in-memory backend.
- Config parsing and validation work for the new hub settings.
- No Valkey-specific types leak into `main_mcp`, health, or MCP hub tool code.

## Step 2 - Add session-namespace and signed callback-token primitives

Files:

- [app/hub/auth.py](../app/hub/auth.py)
- [app/hub/errors.py](../app/hub/errors.py) if a new hub auth error code is needed
- New `tests/unit/test_hub_auth.py`
- [tests/unit/test_auth_permissions.py](../tests/unit/test_auth_permissions.py) only if activity behavior changes

Work:

1. Extend hub auth support beyond static token-to-service lookup by adding
   helpers to mint and validate signed, short-lived callback tokens.
2. Add a keyed `session_namespace` derivation helper so raw `session_id` is not
   required in service-facing hub context.
3. Treat `session_namespace` as the authoritative store scope in service-facing
   callback tokens. Do not require raw `session_id` to cross the service
   boundary.
4. Validate token claims for audience, service principal, allowed operations,
   allowed result types, issue time, not-before time, expiry, and token ID.
5. If raw `session_id` is needed for local correlation, keep that mapping inside
   gofr-agent with the same TTL as the callback token. Store authorization must
   not depend on a non-shared in-memory mapping, because callbacks may arrive on
   a different worker in later deployments.
6. Add bounded fingerprint helpers for session and result logging so logs do not
   expose raw identifiers.
7. Keep this step utility-only. Do not switch the runtime over to the new token
   path until the next steps are in place.

Test gate:

```bash
uv run ruff check app/hub/auth.py app/hub/errors.py tests/unit/test_hub_auth.py tests/unit/test_auth_permissions.py
./scripts/run_tests.sh -k "hub_auth or auth_permissions" -v
```

Exit criteria:

- Valid callback tokens round-trip through mint/validate helpers.
- Expired, malformed, wrong-audience, wrong-service, and wrong-operation tokens
  fail closed.
- Raw session IDs are not required in service-facing token claims or store-scope
   derivation.

## Step 3 - Make the in-memory store session-scoped behind the new protocol

Files:

- [app/hub/store.py](../app/hub/store.py)
- [app/hub/models.py](../app/hub/models.py) only if internal metadata helpers need small changes
- [tests/unit/test_hub_store.py](../tests/unit/test_hub_store.py)

Work:

1. Update `ResultStore` to implement `HubResultStore`.
2. Change `store`, `get`, and `describe` to accept a trusted `HubAccessScope`.
3. Partition in-memory records by `session_namespace` while preserving the
   existing descriptor shape.
4. Enforce `hub_max_results` per session, not globally.
5. Keep TTL, payload-size, summary-size, schema-match, and JSON-serialization
   behavior unchanged.
6. Return a non-revealing unknown-result error when a descriptor is looked up
   from the wrong session scope.

Test gate:

```bash
uv run ruff check app/hub/store.py tests/unit/test_hub_store.py
./scripts/run_tests.sh -k "hub_store" -v
```

Required new tests:

- Same-session store/get/describe still works.
- Cross-session lookup returns unknown result, not a leak.
- Per-session capacity is enforced.
- Descriptors remain session-neutral.
- Expiry still prunes records correctly within a session namespace.

Exit criteria:

- The memory backend now models the intended session-bound behavior.
- Descriptor shape is unchanged.

## Step 4 - Thread trusted session scope through MCP hub tools

Files:

- [app/mcp_server/mcp_server.py](../app/mcp_server/mcp_server.py)
- [app/hub/auth.py](../app/hub/auth.py)
- [tests/unit/test_mcp_server_hub_tools.py](../tests/unit/test_mcp_server_hub_tools.py)
- [tests/integration/test_hub_negative_paths.py](../tests/integration/test_hub_negative_paths.py)

Work:

1. Build `HubAccessScope` inside `_store_result`, `_get_result`, and
   `_describe_result` from validated callback-token claims plus registry-backed
   service capabilities. The store-routing field is `session_namespace`; raw
   `session_id` is runtime-only context and must not be required from callbacks.
2. Enforce service match, allowed operations, and allowed result types before
   calling the store.
3. Pass `scope` to the store for every hub operation.
4. Preserve existing hub protocol payloads and descriptor fields.
5. Add a distinct store-unavailable error path if the generic store interface
   can fail due to dependency outage.

Test gate:

```bash
uv run ruff check app/mcp_server/mcp_server.py app/hub/auth.py tests/unit/test_mcp_server_hub_tools.py tests/integration/test_hub_negative_paths.py
./scripts/run_tests.sh -k "mcp_server_hub_tools or hub_negative_paths" -v
```

Required new tests:

- Valid signed callback token allows publish and consume only within its scope.
- Wrong audience, wrong service, wrong operation, expired token, and missing
  session scope fail closed.
- A descriptor from session A cannot be fetched or described in session B.

Exit criteria:

- Hub tool entrypoints no longer trust raw caller-supplied session information.
- Session scoping is enforced even while still using the memory backend.

## Step 5 - Inject per-call hub context into downstream service sessions

Files:

- [app/services/pool.py](../app/services/pool.py)
- [app/agent/tool_factory.py](../app/agent/tool_factory.py)
- [app/services/registry.py](../app/services/registry.py) if capability registration behavior needs a small adjustment
- [tests/fixtures/mcp_services/_results_hub.py](../tests/fixtures/mcp_services/_results_hub.py)
- Fixture service modules under `tests/fixtures/mcp_services/`
- [tests/integration/test_analytics_hub_integration.py](../tests/integration/test_analytics_hub_integration.py)
- [tests/integration/test_registry_hub_registration.py](../tests/integration/test_registry_hub_registration.py)

Work:

1. Add a small characterization test proving fixture MCP services can read
   per-call inbound headers from the streamable HTTP request context.
2. Extend the downstream one-shot session path so gofr-agent can inject
   per-call outbound hub headers.
3. Mint a session-bound callback token for each downstream tool call that may
   publish or consume hub results.
4. Send at least:
   - `X-GOFR-HUB-URL`
   - `X-GOFR-HUB-CALLBACK-TOKEN`
5. If FastMCP does not expose request headers to fixture tool code, implement
   the reserved non-model-generated hub context fallback before changing
   production behavior.
6. Keep `_register_results_hub` as capability discovery only; do not use it as
   the runtime session-binding mechanism.
7. Update fixture helpers so descriptor-mode hub callbacks use the injected
   per-call context instead of a static process-level token.
8. Remove or quarantine the static-token test path once the per-call flow is
   working end to end.

Test gate:

```bash
uv run ruff check app/services/pool.py app/agent/tool_factory.py app/services/registry.py tests/fixtures/mcp_services/_results_hub.py tests/integration/test_analytics_hub_integration.py tests/integration/test_registry_hub_registration.py
./scripts/run_tests.sh -k "analytics_hub_integration or registry_hub_registration" -v
```

Required new tests:

- Producer service receives valid hub callback context only during the relevant
  user/session-scoped tool call.
- Fixture header propagation is proven or the reserved fallback is covered by
   tests before production code depends on it.
- Consumer service can resolve only descriptors created in the same session.
- Startup registration still reports hub capability correctly without carrying
  session-bound secrets.

Exit criteria:

- Session-bound hub access is propagated through the real downstream tool path.
- Static service-level callback tokens are no longer the security boundary.

## Step 6 - Build the `external_cache` adapter against a fake client first

Files:

- New `app/hub/external_cache_store.py`
- New `app/hub/external_cache_client.py` if a thin client wrapper is useful
- [app/hub/store_factory.py](../app/hub/store_factory.py)
- [pyproject.toml](../pyproject.toml)
- New `tests/unit/test_external_cache_store.py`
- `tests/unit/test_hub_store_factory.py`

Work:

1. Implement the generic external-cache store with adapter-internal key layout
   based on `session_namespace`.
2. Keep cache-specific retry, timeout, reconnect, health probing, and atomic
   write behavior inside the adapter layer.
3. Add the Redis-protocol async client dependency with `uv add` and keep the
   concrete client imports confined to the adapter/client wrapper.
4. Use a fake async cache client for unit tests so the store logic can be
   validated without a container.
5. Enforce:
   - atomic `store`
   - TTL on metadata and payload keys
   - per-session index maintenance
   - stale-record cleanup
   - non-revealing wrong-session behavior
6. Make sure raw `session_id` never appears in generated keys or adapter logs.

Test gate:

```bash
uv run ruff check app/hub/external_cache_store.py app/hub/external_cache_client.py app/hub/store_factory.py tests/unit/test_external_cache_store.py tests/unit/test_hub_store_factory.py
./scripts/run_tests.sh -k "external_cache_store or hub_store_factory" -v
```

Required new tests:

- Atomic store success and atomic failure handling.
- Same-session get/describe.
- Cross-session lookup isolation.
- Stale metadata or payload cleanup.
- Capacity and oversized-payload failure paths.
- Retry budget exhaustion returns store-unavailable.
- Cache keys include `session_namespace`, never raw `session_id`.

Exit criteria:

- The external-cache adapter is correct in isolation before Docker wiring.
- Store selection works for both `memory` and `external_cache`.

## Step 7 - Wire startup, health, and fail-fast behavior to the generic store

Files:

- [app/main_mcp.py](../app/main_mcp.py)
- [app/health.py](../app/health.py)
- [app/mcp_server/mcp_server.py](../app/mcp_server/mcp_server.py) if startup injection changes
- [tests/unit/test_health.py](../tests/unit/test_health.py)
- Add or update unit tests covering startup validation and health payloads

Work:

1. Construct the store through `create_result_store(config)` during startup.
2. Fail startup when `hub_enabled=true`, backend is `external_cache`, and the
   dependency is unavailable.
3. Add startup validation for active-session budget x per-session result budget
   x max payload size.
4. Surface generic store health in startup logs and authenticated
   `health_check`, without leaking credentials or raw session identifiers.
5. Keep health payloads backend-agnostic: `memory` or `external_cache`, status,
   reachable flag, and bounded error text.

Test gate:

```bash
uv run ruff check app/main_mcp.py app/health.py app/mcp_server/mcp_server.py tests/unit/test_health.py
./scripts/run_tests.sh -k "health or main_mcp or hub" -v
```

Required new tests:

- Startup fails fast when external cache is selected but unreachable.
- Startup budget validation rejects inconsistent memory sizing.
- Health output shows generic backend state only.
- Existing hub-disabled and registration-degraded warnings still work.

Exit criteria:

- The app can no longer start in a misleading half-configured external-cache state.
- Operators can see whether the hub store is healthy without backend leakage.

## Step 8 - Add Valkey container wiring for real-server and integration use

Files:

- [docker/compose.dev.yml](../docker/compose.dev.yml)
- [docker/services.compose.dev.yml](../docker/services.compose.dev.yml) for deterministic runtime wiring
- [services.yml.example](../services.yml.example) if config examples need update
- [scripts/start-real-server.sh](../scripts/start-real-server.sh) if the real-server flow should expose the new backend settings
- `tests/integration/` helpers as needed

Work:

1. Add a dedicated Valkey service on the Docker network with volatile-only
   settings and `noeviction`.
2. Wire the real-server dev flow to use Docker service names, not `localhost`.
3. Keep the default test path on the in-memory backend unless a test explicitly
   exercises the external-cache flow.
4. Make the Valkey-backed path easy to enable for real-server testing with the
   existing fixture services.

Test gate:

```bash
bash -n scripts/start-real-server.sh
./scripts/run_tests.sh -k "analytics_hub_integration or registry_hub_registration" -v
```

Manual verification for this step:

1. Start the Valkey-backed dev stack.
2. Confirm the fixture MCP services are healthy on `gofr-net`.
3. Start the real server with `GOFR_AGENT_HUB_STORE_BACKEND=external_cache` and
   a `redis://gofr-agent-valkey:6379/0` cache URL.
4. Confirm startup logs show healthy external-cache state.

Exit criteria:

- Real-server and dev-container flows can run with the new backend topology.
- No service uses `localhost` for container-to-container hub traffic.

## Step 9 - Add end-to-end external-cache and session-isolation integration tests

Files:

- New `tests/integration/test_hub_external_cache_integration.py`
- [tests/integration/test_analytics_hub_integration.py](../tests/integration/test_analytics_hub_integration.py)
- [tests/integration/test_hub_negative_paths.py](../tests/integration/test_hub_negative_paths.py)
- Any focused helpers needed under `tests/helpers/` or `tests/fixtures/`

Work:

1. Add a container-backed integration path that uses the real external-cache
   adapter.
2. Exercise store/get/describe via MCP, not by calling adapter methods directly.
3. Add explicit cross-session isolation tests.
4. Add dependency-failure tests for cache outage, cache flush, and capacity
   pressure.
5. Verify descriptors remain valid only inside the originating session even when
   different services participate in the same user request.

Test gate:

```bash
uv run ruff check tests/integration/test_hub_external_cache_integration.py tests/integration/test_analytics_hub_integration.py tests/integration/test_hub_negative_paths.py
./scripts/run_tests.sh -k "hub_external_cache_integration or analytics_hub_integration or hub_negative_paths" -v
```

Required new tests:

- Happy-path producer -> descriptor -> consumer flow using external cache.
- Cross-session descriptor replay returns unknown result.
- Expired descriptor returns expired result.
- Cache flush or restart yields unknown result, not leaked or partial data.
- Capacity overflow returns `HUB_CAPACITY_EXCEEDED`.
- Store outage returns `HUB_STORE_UNAVAILABLE`.

Exit criteria:

- The end-to-end behavior matches the design in both happy and failure paths.
- Session isolation is proven against the real backend.

## Step 10 - Finish docs, code-quality checks, and full regression

Files:

- [README.md](../README.md)
- [docs/results_hub_cache_design.md](docs/results_hub_cache_design.md) if minor implementation drift needs to be reconciled
- [tests/code_quality/test_code_quality.py](../tests/code_quality/test_code_quality.py) if structural checks need updates
- Any release or developer docs touched by the new config and topology

Work:

1. Update operator/developer docs for the new backend settings and local dev
   flow.
2. Document that phase 1 is volatile-only and not durable storage.
3. Document the health and failure semantics for the external-cache path.
4. Run full code-quality and test validation only after all focused gates are
   green.

Final verification gate:

```bash
uv run ruff check app tests
bash -n scripts/start-real-server.sh scripts/run_tests.sh scripts/start-test-mcp-services.sh
./scripts/run_tests.sh --coverage -v
```

Recommended capture if output is large:

```bash
./scripts/run_tests.sh --coverage -v > tmp/results_hub_cache_full_suite.txt 2>&1
```

Exit criteria:

- Full suite passes.
- README and design docs reflect the shipped behavior.
- The implementation is reviewable as a sequence of small, verified steps.

## Suggested implementation order summary

1. Baseline and characterization tests.
2. Generic config and abstractions.
3. Token and session-namespace primitives.
4. Session-scoped memory store.
5. MCP hub tool scope enforcement.
6. Downstream per-call hub context injection.
7. External-cache adapter unit coverage.
8. Startup and health wiring.
9. Valkey container and end-to-end integration.
10. Docs and full-suite verification.

This order keeps the highest-risk behavior changes isolated: first define the
boundary, then prove session isolation with the memory backend, then swap in the
external cache, and only then promote the full real-server topology.