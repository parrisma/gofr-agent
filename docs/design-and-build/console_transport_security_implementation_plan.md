# GOFR Console Transport Security Implementation Plan

Status: DRAFT - requires user approval before implementation.
Date: 2026-05-17.

Source: `tmp/ui-feedback.md`, "GOFR-Agent Backend Console Contract" draft.

## Goal

Resolve the GOFR Console integration blockers without weakening MCP security:

- Accept known GOFR Console Host and Origin headers for MCP traffic.
- Remove the need for the console Vite proxy to strip `Origin`.
- Preserve bearer-token authentication for MCP tools and chat.
- Keep unauthenticated HTTP health surfaces compact and non-secret.
- Document the final backend answer for the UI team, including any required
  update to [react_integration_guide.md](react_integration_guide.md).

No implementation should start until this plan is approved.

## Current state

1. `app/main_mcp.py` creates the production FastMCP app and adds `/ping` and
   `/health`, but it does not configure FastMCP transport security for the
   production `gofr-agent` MCP server.
2. `scripts/fixture_chat.py` already configures `TransportSecuritySettings` for
   local fixture runs, including a generated `allowed_hosts` list. That pattern
   is useful, but it is not shared with production server startup.
3. `GofrAgentConfig.allowed_service_hosts` exists, but it controls outbound
   runtime service registration. It is not the inbound Host-header allow-list
   for browser or proxy requests to `/mcp`.
4. HTTP `GET /ping` already returns a safe liveness payload.
5. HTTP `GET /health` already returns a compact unauthenticated readiness
   payload. It returns HTTP 200 for `healthy` and `degraded`, and HTTP 503 only
   for `unhealthy`.
6. Authenticated MCP `health_check` already returns detailed model, limits,
   feature, hub, and downstream service diagnostics.
7. The `--no-auth` dev mode is orthogonal to transport security. Disabling auth
   does not loosen FastMCP Host or Origin validation.
8. MCPO (port 8091) wraps the MCP server and may be the actual public surface
   in some deployments. Whatever component faces browsers must enforce the
   same Host and Origin policy on its `/mcp` route.

## Decisions carried into implementation

1. Keep DNS rebinding protection enabled. Fix the allow-lists rather than
   disabling transport security.
2. Add separate inbound MCP config fields. Do not reuse
   `GOFR_AGENT_ALLOWED_SERVICE_HOSTS`.
3. Do not allow wildcard origins when browser requests may include
   `Authorization`.
4. Keep HTTP `/health` compact and unauthenticated. Detailed runtime diagnostics
   remain behind authenticated MCP `health_check`.
5. Keep HTTP `/health` status-code semantics as:
   - `200` for `healthy`
   - `200` for `degraded`
   - `503` for `unhealthy`
6. Treat local browser origins such as `http://localhost:3000` as browser-facing
   development origins only. Service-to-service examples must continue to use
   Docker service names on `gofr-net`.
7. FastMCP transport security applies to the MCP transport handlers only. The
   unauthenticated `/ping` and `/health` routes added by `create_health_routes`
   are plain Starlette routes and are not gated by the Host/Origin allow-list.
   Verify this assumption explicitly in tests; if the version of `mcp` in use
   does apply transport security globally, the plan must include health hosts
   (`gofr-agent-dev`, public health probe host) in `mcp_allowed_hosts`.

## Proposed config contract

Add explicit inbound MCP transport-security settings to `GofrAgentConfig`:

| Field | Environment variable | Purpose |
|-------|----------------------|---------|
| `mcp_allowed_hosts` | `GOFR_AGENT_MCP_ALLOWED_HOSTS` | Comma-separated Host header allow-list for inbound `/mcp` traffic |
| `mcp_allowed_origins` | `GOFR_AGENT_MCP_ALLOWED_ORIGINS` | Comma-separated Origin allow-list for browser/proxy `/mcp` traffic |
| `mcp_dns_rebinding_protection_enabled` | `GOFR_AGENT_MCP_DNS_REBINDING_PROTECTION_ENABLED` | Keep FastMCP DNS rebinding protection enabled by default |
| `cors_allowed_origins` | `GOFR_AGENT_CORS_ORIGINS` | Optional CORS origin allow-list for direct browser access or proxies that forward preflight requests |

Recommended local development values:

```text
GOFR_AGENT_MCP_ALLOWED_HOSTS=gofr-agent-dev,gofr-agent-dev:8090,gofr-agent,gofr-agent:8090,127.0.0.1:*,localhost:*,[::1]:*
GOFR_AGENT_MCP_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://gofr-console-dev:3000
GOFR_AGENT_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://gofr-console-dev:3000
```

Production and shared development deployments must set their actual console
origins and proxy/upstream Host values explicitly. Do not use `*` for origins.

## Implementation steps

### Step 1 - Add inbound MCP transport config

Files:

- Update `app/config.py`.
- Update `tests/unit/test_config.py`.

Work:

1. Add config fields for MCP allowed hosts, MCP allowed origins, DNS rebinding
   protection, and optional CORS origins.
2. Parse the new comma-separated environment variables through the existing
   `GofrAgentConfig.from_env()` helper.
3. Validate origins conservatively:
   - reject `*`
   - require `http` or `https`
   - require a hostname
   - preserve explicit ports
4. Validate hosts conservatively:
   - reject a bare `*`
   - allow exact host, `host:port`, and `host:*` patterns
   - preserve bracketed IPv6 loopback forms such as `[::1]:*`
5. Keep the outbound `allowed_service_hosts` field unchanged.

Acceptance checks:

- Environment parsing returns the expected host and origin lists.
- Wildcard origins are rejected.
- The existing outbound registration allow-list behavior is unchanged.

### Step 2 - Build and apply FastMCP transport security settings

Files:

- Add `app/transport_security.py` or an equivalently focused helper module.
- Update `app/main_mcp.py`.
- Update or add unit tests for the helper.

Work:

1. Add a helper that converts `GofrAgentConfig` into
   `mcp.server.transport_security.TransportSecuritySettings`.
2. Include configured Host and Origin values exactly as FastMCP expects them.
3. Keep `enable_dns_rebinding_protection=True` by default.
4. Apply the settings to the FastMCP instance immediately after
   `create_mcp_server(...)` and before `create_agent_asgi_app(...)` calls
   `mcp.streamable_http_app()`. Update `create_agent_asgi_app` to accept the
   pre-configured FastMCP instance and not re-wrap it.
5. Make the helper reusable by integration tests and local fixture entrypoints.
   Replace the ad-hoc `TransportSecuritySettings(...)` blocks in
   `scripts/fixture_chat.py` and `docker/mcp_fixtures/serve.py` with calls to
   the new helper so production and fixtures cannot drift.
6. Do not log full incoming authorization headers, tokens, or request payloads
   while debugging transport-security failures. Logging a bounded `Host` and
   `Origin` value at debug level is acceptable and useful for operators.

Acceptance checks:

- Production server construction applies `mcp.settings.transport_security`.
- Allowed console Host and Origin combinations can initialize MCP.
- Disallowed Host or Origin values still fail closed.

### Step 3 - Add CORS handling for direct browser and forwarded preflight paths

Files:

- Update `app/main_mcp.py`.
- Reuse `gofr_common.web.CORSConfig` and `create_cors_middleware` if they fit
  the required shape.
- Add or update integration tests around OPTIONS/preflight behavior.

Work:

1. Create a CORS config from `GOFR_AGENT_CORS_ORIGINS` without falling back to a
   permissive wildcard.
2. Allow at least these request headers (case-insensitive at the HTTP layer):
   - `Authorization`
   - `Content-Type`
   - `Accept`
   - `Mcp-Session-Id`
3. Expose `Mcp-Session-Id` on responses so the MCP TypeScript SDK can read it.
4. Keep CORS middleware outermost. Final ASGI stack order must be:
   `CORSMiddleware(AuthHeaderMiddleware(starlette_app_with_health_routes))`.
   Preflight requests must not require bearer auth or a valid MCP session.
5. Keep `AuthHeaderMiddleware` in place for MCP tool execution.
6. If `GOFR_AGENT_CORS_ORIGINS` is empty, do not install CORS middleware at
   all. Same-origin proxy deployments (Vite, nginx) do not need it and adding
   permissive defaults would weaken security.

Acceptance checks:

- OPTIONS preflight from an allowed console origin returns the expected CORS
  headers.
- Preflight from a disallowed origin does not grant CORS access.
- MCP initialize still returns `Mcp-Session-Id`.

### Step 4 - Preserve and polish HTTP health behavior

Files:

- Update `app/health.py` only if needed.
- Update `tests/unit/test_health.py` and HTTP integration tests if behavior is
  changed.

Work:

1. Keep `/ping` and `/health` unauthenticated.
2. Add `Cache-Control: no-store` to `/ping` and `/health` responses by passing
   `headers={"Cache-Control": "no-store"}` to `JSONResponse` in
   `create_health_routes`.
3. Keep `/ping` dependency-free and network-free.
4. Keep `/health` compact:
   - `status`
   - `service`
   - `timestamp`
   - `version`
   - `message`
   - downstream counts
5. Do not add model names, model override lists, feature flags, service URLs,
   service item details, tokens, prompts, raw errors, or session content to
   unauthenticated `/health`.
6. Keep detailed diagnostics in authenticated MCP `health_check`.
7. Keep HTTP status code `200` for `degraded` unless the user explicitly
   approves changing readiness semantics.

Acceptance checks:

- `/ping` returns `200`, `status: ok`, `service: gofr-agent`, and no-store.
- `/health` returns `200` for healthy and degraded states.
- `/health` returns `503` only for unhealthy core readiness failures.
- `/health` does not expose raw secret sentinel values or detailed service
  config.

### Step 5 - Add end-to-end console-shaped MCP tests

Files:

- Update `tests/integration/test_mcp_server_integration.py` or add a focused
  integration test module.
- Add small test helpers if needed for browser/proxy-shaped headers.

Work:

1. Start an in-process `gofr-agent` MCP app with the new transport-security
   config.
2. Send an MCP initialize request with headers shaped like the console proxy
   path:
   - `Host: gofr-agent-dev:8090` or the value the backend actually receives
   - `Origin: http://localhost:3000`
   - `Content-Type: application/json`
   - `Accept: application/json, text/event-stream`
   - `Authorization: Bearer dev-admin-token` (existing dev token in
     `tests/helpers/dummy_auth_service.py`)
3. Assert successful initialize, SSE response body, and `Mcp-Session-Id`
   (response-header lookup must be case-insensitive).
4. Call MCP `ping` or `health_check` with the returned session id.
5. Repeat with a disallowed Origin and assert rejection.
6. Repeat with a disallowed Host and assert rejection.
7. Repeat with a missing or invalid bearer token and assert MCP tool execution
   still fails closed.

Acceptance checks:

- Valid console-shaped traffic no longer triggers invalid Host or Origin
  rejection.
- Invalid Host, invalid Origin, and invalid token are distinguishable failure
  modes.
- The tests do not depend on `localhost` for container-to-container traffic.

### Step 6 - Update development and deployment configuration

Files:

- Update the active dev container or compose scripts that launch `gofr-agent`.
- Update README and platform docs as needed.
- If `docker/compose.dev.yml` is still a copied template for another GOFR
  service, do not rely on it as the only source of truth; fix the actual launch
  path used by `gofr-agent`.

Work:

1. Set local development allowed hosts and origins for the console topology.
2. Document the production environment variables operators must set.
3. Include examples for:
   - Vite same-origin proxy to `http://gofr-agent-dev:8090/mcp`
   - deployed console origin through a reverse proxy
   - direct browser-to-agent development only when explicitly configured
4. Confirm examples use Docker service names for service-to-service paths.
5. Do not document `localhost` as a container-to-container target.

Acceptance checks:

- Local dev starts with known console Host and Origin values allowed.
- Production docs require explicit public/proxy Host and Origin values.
- The console workaround can be removed for current `gofr-agent` images after
  the backend change is deployed.

### Step 7 - Documentation and UI-team reply

Files:

- Update [react_integration_guide.md](react_integration_guide.md).
- Optionally add a short `docs/console_backend_contract_reply.md` if the reply
  should be preserved separately.

Work:

1. Update the React guide with the final accepted backend contract:
   - MCP Host and Origin allow-list requirements
   - exact environment variables
   - `421 Invalid Host header` handling
   - invalid Origin handling
   - CORS/preflight expectations
   - compact HTTP `/health` versus authenticated MCP `health_check`
   - `200` for degraded HTTP health, unless explicitly changed before approval
2. Draft a reply to the GOFR Console/UI team. The reply should say:
   - backend will accept the known console Host and Origin values explicitly
   - the console should remove Origin stripping after the backend version lands
   - the browser should continue to call the same-origin console proxy
   - MCP chat and tools remain bearer-authenticated
   - unauthenticated `/ping` and `/health` are compact and safe
   - detailed runtime diagnostics are available through MCP `health_check`
   - degraded downstream services remain HTTP 200 with JSON `status: degraded`
   - invalid tokens still fail closed
3. Include the validation commands the UI team can run, adjusted to the final
   health status semantics.

Acceptance checks:

- The React guide matches implemented behavior.
- The UI reply identifies what changed in the backend and what workaround the
  UI can remove.
- The UI reply does not ask the browser to set or spoof the `Host` header.

## Validation plan

Run targeted tests first:

```bash
./scripts/run_tests.sh tests/unit/test_config.py tests/unit/test_health.py -v
./scripts/run_tests.sh tests/unit/test_transport_security.py -v
./scripts/run_tests.sh tests/integration/test_mcp_server_integration.py -v
```

Then run quality and full suite:

```bash
./scripts/run_tests.sh --quality
./scripts/run_tests.sh -v
```

If full-suite output is too large, redirect it to `tmp/full_suite_console_transport.txt`
and inspect the tail.

Manual smoke after backend and console configuration are both updated:

```bash
curl -sS -i --max-time 5 http://gofr-agent-dev:8090/ping
curl -sS -i --max-time 5 http://gofr-agent-dev:8090/health
```

Browser-shaped MCP initialize through the console proxy:

```bash
curl -sS -i --max-time 10 \
  -H 'Host: localhost:3000' \
  -H 'Origin: http://localhost:3000' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Authorization: Bearer dev-admin-token' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"gofr-console-smoke","version":"0.0.1"}}}' \
  http://gofr-console-dev:3000/api/gofr-agent/mcp
```

Log check:

```bash
docker logs --since 2m gofr-agent-dev 2>&1 | grep -E 'Invalid (Origin|Host) header' || true
```

Expected result: no matches for valid console-origin traffic.

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Accidentally allowing arbitrary browser origins | Reject `*` origins and require explicit configured origins |
| Confusing inbound Host allow-list with outbound service registration allow-list | Use new config names and document the distinction |
| CORS preflight blocked by auth middleware | Put CORS middleware outermost and test OPTIONS explicitly |
| Load balancer removes degraded but still usable agent | Keep HTTP 200 for degraded; put degraded state in JSON |
| UI keeps Origin-stripping workaround after backend fix | Final stage includes React guide update and direct UI reply |
| Production proxy rewrites Host differently than expected | Document that operators must allowlist the Host value received by `gofr-agent`, not only the browser URL |

## Open questions for approval

1. Confirm the final local development Host values that `gofr-agent` actually
   receives through the console proxy. The draft assumes `gofr-agent-dev:8090`
   and `gofr-agent:8090` are required.
2. Confirm whether local development CORS origins should be configured in the
   dev launch scripts only, or whether they should also be default values in
   `GofrAgentConfig`.
3. Confirm that HTTP `/health` remains compact and returns HTTP 200 for
   degraded downstream service state. This plan recommends keeping the current
   behavior.
4. Confirm whether the UI-team reply should be a new docs file, an update to
   [react_integration_guide.md](react_integration_guide.md), or both.
5. Confirm whether MCPO (port 8091) is in scope. If MCPO is the browser-facing
   surface in any deployment, it must enforce the same Host/Origin contract.
6. Confirm the Host value that `gofr-agent` actually receives when traffic
   arrives through the Vite proxy. The console feedback shows both
   `http://localhost:3000` and `http://gofr-agent-dev:8090` as flagged origins;
   this must be re-measured after the backend change so the allow-list matches
   the proxy's forwarded Host, not just the URL the browser typed.