# gofr-agent Health Check Implementation Plan

Status: DRAFT - requires user approval before implementation.
Date: 2026-05-17.

Spec: [agent_health_check_spec.md](agent_health_check_spec.md)

## Goal

Add gofr-iq-style ping and health-check capability to gofr-agent:

- HTTP `GET /ping` for minimal process reachability.
- HTTP `GET /health` for safe orchestrator readiness.
- MCP `ping` kept backward-compatible and enriched with `service`.
- MCP `health_check` for authenticated detailed diagnostics, including selected
  model, allowed model overrides, sanitized config settings, service registry
  status, and results-hub capability state.

No implementation should start until this plan is approved.

## gofr-iq findings to carry forward

1. `../gofr-iq/app/web_server/web_server.py` exposes simple HTTP `/health` and
   `/ping` routes returning process metadata.
2. `../gofr-iq/app/main_mcp.py` adds an HTTP `/health` route to the MCP
   Starlette app because Streamable HTTP `/mcp` is session-oriented and awkward
   as a load-balancer health target.
3. `../gofr-iq/app/tools/health_tools.py` exposes an MCP `health_check` tool
   that returns an overall status plus per-dependency detail.
4. gofr-iq exposes model names and API-key configured booleans, but not secret
   values. gofr-agent should follow that pattern.

## Implementation steps

### Step 1 - Add health payload builders

Files:

- Add `app/health.py`.
- Unit test with `tests/unit/test_health.py`.

Work:

1. Create `build_ping_payload()` returning `status`, `service`, `timestamp`, and
   `version`.
2. Create `build_health_payload(config, registry, agent, result_store=None)`
   returning the detailed schema from the spec.
3. Create small helpers for:
   - sanitized model config
   - limits config
   - session config
   - feature flags
   - hub config
   - downstream service summary
   - overall status/message
4. Use only safe data already available from `GofrAgentConfig`,
   `ServiceRegistry`, and `app.__version__`.
5. Do not call downstream network services from the health builder.
6. Bound any service error strings included in the output. Suggested maximum:
   512 characters.

Acceptance checks:

- Empty registry produces a valid `healthy` payload with `total=0` and a clear
  message.
- Healthy, degraded, and failed service combinations produce expected counts and
  status.
- Config payload includes selected model and `openrouter_api_key_configured` as
  a boolean only.
- No key field contains `token`, `secret`, `password`, or raw API-key material.

### Step 2 - Add HTTP `/ping` and `/health` routes

Files:

- Update `app/main_mcp.py`.
- Add or extend integration/unit tests around the Starlette app construction.

Work:

1. In `_run_server()`, build the FastMCP Starlette app before wrapping it in
   `AuthHeaderMiddleware`.
2. Append HTTP routes for `/ping` and `/health` to that app.
3. Keep `/ping` minimal and always return HTTP 200 when the process can respond.
4. Keep `/health` safe for unauthenticated orchestrators. It should include a
   compact subset: status, service, timestamp, version, message, and downstream
   counts.
5. Return HTTP 200 for `healthy` and `degraded`; return HTTP 503 only for
   `unhealthy`.
6. Wrap the app with `AuthHeaderMiddleware` after adding routes so MCP tools
   still receive auth context and HTTP health routes remain reachable.

Notes:

- Prefer a local route factory in `app/health.py` over embedding route closures
  in `main_mcp.py`, unless the final code is clearer with closures.
- `gofr_common.web.create_health_routes()` is useful as a pattern, but it does
  not expose the richer downstream summary required here. Do not force-fit it.

Acceptance checks:

- `GET /ping` returns `service=gofr-agent` and `status=ok` without MCP session
  setup.
- `GET /health` returns the compact health payload without requiring a bearer
  token.
- MCP `/mcp` auth behavior is unchanged.

### Step 3 - Add MCP `health_check` tool

Files:

- Update `app/mcp_server/mcp_server.py`.
- Update `app/auth/permissions.py`.
- Update `app/auth/__init__.py`.
- Update `app/auth/_dev_auth_service.py`.
- Update test helpers that enumerate `ALL_ACTIVITIES` if needed.

Work:

1. Add `AGENT_HEALTH_CHECK = "GoFRAgentHealthCheck"`.
2. Add it to `ALL_ACTIVITIES`.
3. Include it in the dev admin token activities.
4. Decide whether the dev read token gets `health_check`. Recommended: yes,
   because the payload is sanitized and diagnostic, but this should be called
   out in tests.
5. Register `@mcp.tool()` named `health_check` in `create_mcp_server()`.
6. The first statement inside the tool must be
   `_guard(auth_service, AGENT_HEALTH_CHECK)`.
7. Return the detailed payload from `build_health_payload()`.
8. Give the tool a description modelled on gofr-iq: use it when tool calls fail,
   services seem slow, or a client needs runtime diagnostics.

Acceptance checks:

- Authorized caller receives model/config/service diagnostics.
- Missing token is rejected.
- Caller without `GoFRAgentHealthCheck` is rejected.
- `health_check` output contains no secret-bearing fields.

### Step 4 - Keep MCP `ping` compatible and enrich it

Files:

- Update `app/mcp_server/mcp_server.py`.
- Update tests in `tests/unit/test_mcp_server.py` and
  `tests/integration/test_mcp_server_integration.py`.

Work:

1. Replace the current hand-built MCP ping payload with the shared
   `build_ping_payload()` helper.
2. Preserve existing fields: `status`, `timestamp`, `version`.
3. Add `service: "gofr-agent"`.
4. Keep existing auth requirement `GoFRAgentPing`.

Acceptance checks:

- Existing ping tests still pass after adding the `service` assertion.
- Existing clients that only check `status`, `timestamp`, and `version` remain
  compatible.

### Step 5 - Add tests for health status computation

Files:

- `tests/unit/test_health.py`
- `tests/unit/test_mcp_server.py`
- `tests/integration/test_mcp_server_integration.py`

Unit coverage:

1. `build_ping_payload()` shape.
2. `build_health_payload()` with no downstream services.
3. All-healthy downstream service state.
4. Degraded pool state.
5. Failed service with bounded error message.
6. Hub-enabled config with `hub_url_configured=true` but without exposing the
   actual callback token values.
7. Model config with `llm_model`, `allowed_models`, and
   `openrouter_api_key_configured` boolean.
8. Secret-redaction guard that recursively fails if sensitive key names or known
   secret sentinel values appear in the payload.

MCP tool coverage:

1. `health_check` authorized.
2. `health_check` denied without token.
3. `health_check` denied when activity missing.
4. `ping` now includes `service`.

Integration coverage:

1. Real MCP client calls `health_check` through Streamable HTTP.
2. Real MCP client calls `ping` through Streamable HTTP and sees `service`.
3. HTTP `GET /ping` returns 200.
4. HTTP `GET /health` returns 200 and compact downstream counts.

### Step 6 - Update docs

Files:

- `README.md`
- `docs/current_state.md`
- `docs/master_specification.md`
- `docs/react_integration_guide.md`

Work:

1. Add `health_check` to the MCP tools table.
2. Document HTTP `/ping` and `/health` as process/orchestrator endpoints.
3. Document the detailed MCP health payload and its secret-redaction contract.
4. Update React guidance to prefer `health_check` for a diagnostics/settings
   panel and `/ping` or MCP `ping` for lightweight connectivity checks.

### Step 7 - Validation

Run targeted tests first:

```bash
./scripts/run_tests.sh tests/unit/test_health.py tests/unit/test_mcp_server.py -v
./scripts/run_tests.sh tests/integration/test_mcp_server_integration.py -v
```

Then run quality and full suite:

```bash
./scripts/run_tests.sh --quality
./scripts/run_tests.sh -v
```

If any test fails because existing unrelated behavior is broken, stop and report
the failure with the failing test, command, and evidence before widening scope.

## Proposed implementation order

1. Health payload builder and unit tests.
2. MCP `health_check` activity and tool.
3. MCP `ping` shared payload update.
4. HTTP `/ping` and `/health` route integration.
5. Integration tests.
6. Docs.
7. Quality and full suite validation.

## Open questions for approval

1. Should the dev read token include `GoFRAgentHealthCheck`? Recommendation:
   yes, because the payload is sanitized and useful for UI/LLM diagnostics.
2. Should HTTP `/health` include model/config details, or should those remain
   only in authenticated MCP `health_check`? Recommendation: keep HTTP compact
   and expose detailed model/config state only through MCP `health_check`.
3. Should zero downstream services be `healthy` with a warning message or
   `degraded`? Recommendation: `healthy`, because starting without a services
   manifest is a supported degraded-capability mode rather than a process
   failure.
