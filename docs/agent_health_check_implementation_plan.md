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

## Peer-review amendments

1. Health service items must be built from an explicit allow-list. Do not reuse
   `ServiceConfig.safe_dump()` for health output, because it intentionally keeps
   non-secret config plumbing such as URLs, `token_env`, and
   `hub_callback_token_env` that the health spec does not allow.
2. Add a public readiness signal on `GofrAgent` rather than inspecting the
   private `_agent` attribute from the health module.
3. Keep HTTP route assembly reusable. The production server and HTTP health
   integration tests should build the Starlette app through the same helper so
   the tests exercise the same `/ping`, `/health`, and auth-middleware ordering
   as `app.main_mcp`.
4. Treat downstream service failures and results-hub registration errors as
   `degraded`, not `unhealthy`. Reserve `unhealthy` for core construction or
   readiness failures that prevent normal MCP operation.
5. For new or edited MCP tools, pass long descriptions through the FastMCP
   decorator so `_guard(...)` remains the first executable statement in the tool
   body.

## Implementation steps

### Step 1 - Add health payload builders

Files:

- Add `app/health.py`.
- Update `app/agent/agent.py` only to add a read-only readiness property if
  needed.
- Unit test with `tests/unit/test_health.py`.

Work:

1. Create `build_ping_payload()` returning `status`, `service`, `timestamp`, and
   `version`.
2. Create `build_health_payload(config, registry, agent)`
   returning the detailed schema from the spec.
3. Create small helpers for:
   - sanitized model config
   - limits config
   - session config
   - feature flags
   - hub config
   - downstream service summary
   - overall status/message
4. Build downstream service item dictionaries from an explicit key allow-list:
   `name`, `status`, `tool_count`, results-hub capability booleans,
   `result_types`, and bounded `error` / `registration_error` when present.
   Do not include service URLs, token fields, token env-var names, descriptions,
   or raw manifest/config dumps.
5. Use only safe data already available from `GofrAgentConfig`,
   `ServiceRegistry`, `GofrAgent` readiness, and `app.__version__`.
6. Add a simple `GofrAgent.is_built` property if the health builder needs to
   distinguish ready from not-yet-built agents.
7. Do not call downstream network services from the health builder.
8. Bound any service error strings included in the output. Suggested maximum:
   512 characters.
9. Treat any service `registration_error` from
   `registry.service_hub_capabilities(name)` as a degraded downstream condition
   and include the bounded message only in the authenticated MCP payload.

Acceptance checks:

- Empty registry produces a valid `healthy` payload with `total=0` and a clear
  message.
- Healthy, degraded, and failed service combinations produce expected counts and
   status; failed downstream services produce overall `degraded`, not
   `unhealthy`.
- Hub registration errors produce overall `degraded` even when the service pool
   itself is otherwise healthy.
- An unbuilt agent produces an `unhealthy` payload with a clear bounded message.
- Config payload includes selected model and `openrouter_api_key_configured` as
  a boolean only.
- Detailed downstream service item keys match the explicit allow-list above.
- No raw secret sentinel value appears anywhere in the payload. Redaction tests
   may allow boolean `*_configured` fields such as
   `openrouter_api_key_configured`, but must reject raw keys, tokens, passwords,
   callback tokens, and secret values.

### Step 2 - Add HTTP `/ping` and `/health` routes

Files:

- Update `app/main_mcp.py`.
- Add route helpers in `app/health.py` or a tiny shared app-construction helper
   near `app/main_mcp.py`.
- Add or extend integration/unit tests around the Starlette app construction.

Work:

1. Add a reusable helper that builds the ASGI app in this order:
   `mcp.streamable_http_app()`, append health routes, then wrap with
   `AuthHeaderMiddleware`.
2. Use that helper from `_run_server()` and from the HTTP health integration
   tests.
3. Keep `/ping` minimal and always return HTTP 200 when the process can respond.
4. Keep `/health` safe for unauthenticated orchestrators. It should include a
   compact subset: status, service, timestamp, version, message, and downstream
   counts.
5. Return HTTP 200 for `healthy` and `degraded`; return HTTP 503 only for
   `unhealthy`.
6. Wrap the app with `AuthHeaderMiddleware` after adding routes so MCP tools
   still receive auth context and HTTP health routes remain reachable.
7. If detailed health construction raises unexpectedly, the HTTP route should
   return a compact `unhealthy` payload with HTTP 503 and without traceback or
   secret-bearing details.

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
- Tests construct the app through the same helper as production.

### Step 3 - Add MCP `health_check` tool

Files:

- Update `app/mcp_server/mcp_server.py`.
- Update `app/auth/permissions.py`.
- Update `app/auth/__init__.py`.
- Update `app/auth/_dev_auth_service.py`.
- Update `tests/helpers/dummy_auth_service.py`.
- Update auth tests that enumerate `ALL_ACTIVITIES` or dev/read-token contents.

Work:

1. Add `AGENT_HEALTH_CHECK = "GoFRAgentHealthCheck"`.
2. Add it to `ALL_ACTIVITIES`.
3. Include it in the dev admin token activities.
4. Add it to the dev admin token and to the dev read token. The read-token grant
   is intentional because the payload is sanitized and is useful for UI/LLM
   diagnostics.
5. Register `@mcp.tool(name="health_check", description=...)` in
   `create_mcp_server()`.
6. The first executable statement inside the tool must be
   `_guard(auth_service, AGENT_HEALTH_CHECK)`.
7. Return the detailed payload from `build_health_payload()`.
8. Give the tool a description modelled on gofr-iq: use it when tool calls fail,
   services seem slow, or a client needs runtime diagnostics.

Acceptance checks:

- Authorized caller receives model/config/service diagnostics.
- Missing token is rejected.
- Caller without `GoFRAgentHealthCheck` is rejected.
- `dev-read-token` can call `health_check`; document this in auth tests.
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
5. When touching the tool, move the description to the decorator if needed so
   `_guard(auth_service, AGENT_PING)` is the first executable statement.

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
6. Hub registration error degrades status and bounds `registration_error`.
7. Hub-enabled config with `hub_url_configured=true` but without exposing the
   actual callback token values.
8. Model config with `llm_model`, `allowed_models`, and
   `openrouter_api_key_configured` boolean.
9. Agent not built yields `unhealthy`.
10. Explicit downstream service allow-list excludes URL, `token_env`,
    `hub_callback_token_env`, descriptions, and raw service config.
11. Secret-redaction guard that recursively fails if known secret sentinel values
    or non-allow-listed sensitive key names appear in the payload.

MCP tool coverage:

1. `health_check` authorized.
2. `health_check` denied without token.
3. `health_check` denied when activity missing.
4. `health_check` allowed with the dev read token.
5. `ping` now includes `service`.

Integration coverage:

1. Real MCP client calls `health_check` through Streamable HTTP.
2. Real MCP client calls `ping` through Streamable HTTP and sees `service`.
3. HTTP `GET /ping` returns 200 without an Authorization header.
4. HTTP `GET /health` returns 200 and compact downstream counts.
5. HTTP `GET /health` returns 200 for degraded downstream state and 503 only for
   a core unhealthy state.

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
./scripts/run_tests.sh tests/unit/test_health.py tests/unit/test_mcp_server.py tests/unit/test_auth.py tests/unit/test_auth_permissions.py -v
./scripts/run_tests.sh tests/integration/test_mcp_server_integration.py tests/integration/test_auth_integration.py -v
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
2. Agent readiness property, if needed by the builder.
3. MCP `health_check` activity and tool.
4. MCP `ping` shared payload update.
5. HTTP `/ping` and `/health` route integration.
6. Integration tests.
7. Docs.
8. Quality and full suite validation.

## Open questions for approval

1. Should HTTP `/health` include model/config details, or should those remain
   only in authenticated MCP `health_check`? Recommendation: keep HTTP compact
   and expose detailed model/config state only through MCP `health_check`.
2. Should zero downstream services be `healthy` with a warning message or
   `degraded`? Recommendation: `healthy`, because starting without a services
   manifest is a supported degraded-capability mode rather than a process
   failure.
