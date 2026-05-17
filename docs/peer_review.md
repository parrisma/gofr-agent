# gofr-agent — Senior Engineer Peer Review

Status: Historical review snapshot. It remains useful for unresolved
operational-hardening themes, but it predates the completed prompt-hardening
and results-hub closeout captured in [docs/current_state.md](current_state.md).

Reviewer perspective: senior software engineer + agentic-AI design SME.
Scope: design and implementation of `gofr-agent` as of the current `main`
working tree (base commit `8058a03`).
Goal: identify the remaining improvements that are still worth planning after
the reasoning-stream hardening work already landed.

This document is intentionally review-only. It has been pruned to remove
findings already addressed on current `main`, including:

- tool-result sentinels and system-prompt safety guidance;
- request correlation ids and hot-path structured logging migration;
- `ask` input validation and bounded `max_steps`;
- outer agent timeout;
- derived reasoning `steps` plus live MCP reasoning notifications;
- bounded session count/history with rolling summaries;
- structured downstream tool errors and bounded retries;
- dynamic registration allow-listing and health probing;
- CLI streaming, `--format json`, and richer verbose output.

---

## 1. Executive summary

Top remaining issues, in rough order of severity:

1. **MCP error semantics are still too coarse.** Auth and service-side errors
   still collapse to `INVALID_PARAMS`, so clients cannot distinguish caller
   mistakes from infrastructure failures (`app/mcp_server/mcp_server.py`).
2. **Service lifecycle controls remain incomplete.** Startup manifest failures
   are still skipped rather than surfaced in `list_services`; there is still no
   `reload_manifest` tool and no shutdown guard blocking new registrations while
   the registry is tearing down (`app/services/registry.py`).
3. **`config.py` and `settings.py` still overlap.** The project now has a clear
   live config path, but the legacy wrapper remains and continues to invite
   confusion (`app/config.py`, `app/settings.py`).
4. **No rate limiting or inflight-request drain.** The reasoning path is better
   bounded than before, but a burst of requests can still overwhelm the process
   and shutdown still does not wait for active `ask` calls to finish.
5. **Observability is still mostly logs and events.** There is no metrics layer,
   no tracing, and no per-step cost telemetry beyond the final token total.
6. **Dev auth and failure testing lag the new policy surface.** Dev tokens are
   still hard-coded, wildcard downstream grants are still under-documented, and
   the integration test matrix still lacks malformed/timeout downstream tools.

The architecture remains sound. The biggest review items from the earlier pass
have already been addressed; what remains is mostly operational hardening,
cleanup, and DX polish.

---

## 2. Findings by dimension

Severity legend: **Critical** (security or correctness), **High** (reliability
or operability), **Medium** (maintainability or DX), **Low / Nit** (polish).

Original finding IDs are retained where practical for traceability.

### 2.1 Architecture and layering

| # | Sev | Finding | Recommendation |
|---|-----|---------|----------------|
| 2.1.1 | Medium | `_guard()` still lives in `app/mcp_server/mcp_server.py` even though it is an auth concern. | Move `_guard` (or an equivalent decorator/helper) into `app/auth/` so MCP tool definitions stay declarative. |
| 2.1.2 | Medium | `app/agent/tool_factory.py` still reaches into `pool.open_user_session()` and `session.call_tool()` directly. | Expose a higher-level tool-call API on the pool so the factory depends on service semantics rather than connection mechanics. |
| 2.1.3 | Low | `app/services/models.py` still re-exports symbols already re-exported from `app/services/__init__.py`. | Pick one re-export site and remove the duplicate. |

### 2.2 Agent loop design

| # | Sev | Finding | Recommendation |
|---|-----|---------|----------------|
| 2.2.5 | Medium | Token / cost telemetry is still final-only. `tokens_used` is surfaced at the end of the run, but no per-step or per-tool breakdown is logged or emitted. | Capture deltas if pydantic-ai exposes them cleanly; otherwise log structured totals around model and tool phases so operators can reason about cost hotspots. |

### 2.3 Tool factory and schema handling

| # | Sev | Finding | Recommendation |
|---|-----|---------|----------------|
| 2.3.2 | High | Discovered `inputSchema` objects are still trusted at discovery time and only fail once the generated tool is exercised. | Validate schema shape during discovery/build; skip bad tools explicitly and surface them as degraded. |

### 2.4 Service registry, pool, discovery

| # | Sev | Finding | Recommendation |
|---|-----|---------|----------------|
| 2.4.1 | High | Dynamic-registration failures are now represented, but startup manifest failures are still only logged and skipped. Operators cannot see them in `list_services`. | Record failed manifest services with `failed` status and error text, just like failed runtime registrations. |
| 2.4.3 | Medium | There is still no way to reload `services.yml` without restarting the server. | Add a `reload_manifest` MCP tool, gated by a new activity. |
| 2.4.4 | Medium | `ServiceRegistry.shutdown()` still does not block new `register_service` calls. | Add a `_shutting_down` flag and reject registration attempts once shutdown begins. |
| 2.4.5 | Low | The pool's lock/connect interleaving is still correct but non-obvious. | Add a short explanatory comment in `_open_slot` to make the concurrency contract obvious to future maintainers. |

### 2.6 MCP server tool surface

| # | Sev | Finding | Recommendation |
|---|-----|---------|----------------|
| 2.6.1 | High | `_guard()` still maps invalid token, denied activity, and auth-backend outage to `INVALID_PARAMS`. | Map validation errors to `INVALID_PARAMS`, auth failures to a request/auth category, and downstream/service failures to internal/server errors. |
| 2.6.5 | Low | Tool response shapes are still inconsistent (`dict`, `list`, ad hoc payloads). | Decide whether a uniform envelope is actually desired; if yes, introduce it consistently instead of tool-by-tool drift. |

### 2.7 Auth

| # | Sev | Finding | Recommendation |
|---|-----|---------|----------------|
| 2.7.1 | Medium | Dev token handling is still hard-coded and now lags the live activity surface. `DevAuthService` does not include newer activities such as `AGENT_MODEL_OVERRIDE`. | Make the dev token set configurable or at least keep it in lockstep with `ALL_ACTIVITIES`; document that it is dev-only. |
| 2.7.2 | Medium | The project still assumes `gofr_common` validates JWT audience/issuer/expiry correctly; there is still no focused integration test proving it. | Add an integration test with a wrong-audience token and assert rejection. |
| 2.7.3 | Low | The wildcard `MCPServer*` grant in dev auth is still under-documented. | Add a short warning in README and/or expand the dev-auth docstring so the blast radius is explicit. |

### 2.8 Configuration and env handling

| # | Sev | Finding | Recommendation |
|---|-----|---------|----------------|
| 2.8.1 | High | `app/settings.py` and `app/config.py` still overlap conceptually. | Delete `settings.py`, or make it the single authoritative config entry point and delete `config.py`. Pick one. |

### 2.9 Exceptions and error model

| # | Sev | Finding | Recommendation |
|---|-----|---------|----------------|
| 2.9.2 | Low | `ToolResultTruncatedWarning` is still defined but never raised. | Either emit/raise it from the truncation path or remove it. |
| 2.9.3 | Medium | Broad `except Exception` catch sites still exist on the hot path and in service discovery/pool management. | Narrow catches to domain exceptions where possible; let unexpected faults bubble to a top-level handler that logs traceback. |

### 2.10 Observability

| # | Sev | Finding | Recommendation |
|---|-----|---------|----------------|
| 2.10.3 | Medium | There are still no metrics for tool-call latency, success rate, or service health transitions. | Wrap downstream tool calls and registry/pool state transitions in a small metrics layer. |
| 2.10.4 | Medium | There are still no tracing hooks (OpenTelemetry or similar). | Add optional tracing around `ask`, model phases, pool checkout, and downstream tool calls. |

### 2.11 Testing strategy

| # | Sev | Finding | Recommendation |
|---|-----|---------|----------------|
| 2.11.3 | Medium | The mock MCP server is still almost entirely happy-path. It does not model malformed responses, long hangs, or explicit server-side failures. | Add dedicated error tools and use them in integration tests for retries, malformed payload handling, and pool failure semantics. |

### 2.12 Security

| # | Sev | Finding | Recommendation |
|---|-----|---------|----------------|
| 2.12.3 | High | There is still no rate limiting per token or IP. | Add a sliding-window limiter (in-memory is acceptable for v1) or define that this must be handled by an upstream gateway. |
| 2.12.5 | Low | Service tokens still live in plaintext in process memory, and the codebase still does not document that pool state must never be serialised. | Add an explicit note to the pool/service-token docs. |

### 2.13 Robustness and resilience

| # | Sev | Finding | Recommendation |
|---|-----|---------|----------------|
| 2.13.3 | Medium | Graceful shutdown still does not drain inflight `ask` calls before process exit. | Track inflight requests and wait up to a configured grace period before shutdown completes. |

### 2.14 Performance and scalability

| # | Sev | Finding | Recommendation |
|---|-----|---------|----------------|
| 2.14.2 | Medium | The system prompt is still rebuilt on every `agent.build()` even when service descriptors have not changed. | Cache the rendered prompt and invalidate only when the registry changes. |
| 2.14.3 | Medium | Tool-result truncation still constructs the entire string in memory before trimming it. | Stream-truncate when the underlying client supports chunked reads, or at least cap accumulation more aggressively. |

### 2.15 Developer experience

| # | Sev | Finding | Recommendation |
|---|-----|---------|----------------|
| 2.15.1 | Medium | There is still no short guide for authoring a downstream MCP service that plugs into gofr-agent. | Add a concise doc with a minimal MCP service example plus the corresponding manifest entry. |
| 2.15.2 | Medium | Several user-facing errors still bubble up as raw `str(exc)` strings. | Wrap operator-facing and user-facing messages separately; include remediation hints where practical. |
| 2.15.3 | Low | `app.cli.ask` is still a one-shot command; the REPL lives in `scripts/fixture_chat.py` and is specialised for the fixture stack. | Decide whether a generic `--interactive` mode belongs in the main CLI, or document that fixture chat is the intended manual REPL. |

### 2.16 Code quality

| # | Sev | Finding | Recommendation |
|---|-----|---------|----------------|
| 2.16.1 | Medium | `agent.py` still carries `# type: ignore[arg-type]` on the tool list without an explanatory comment. | Add a short note explaining the pydantic-ai typing mismatch. |
| 2.16.2 | Low | `pool.py` still has magic numbers such as `20` attempts in `_find_live_slot`. | Extract named constants. |
| 2.16.3 | Low | `Session` remains a dataclass with no invariants beyond ad hoc helper methods. | Either add validation/invariant checks or move to a small validated model. |

---

## 3. Recommended roadmap

The roadmap is grouped by impact vs effort, not by strict dependency order.

### Phase 1 — Quick wins

1. Map MCP errors to meaningful categories instead of collapsing to
   `INVALID_PARAMS`. [2.6.1]
2. Remove the `config.py` / `settings.py` split. [2.8.1]
3. Validate discovered tool schemas and surface bad tools explicitly. [2.3.2]
4. Surface startup manifest registration failures in `list_services`. [2.4.1]
5. Bring `DevAuthService` back into sync with the live activity model and
   document wildcard downstream access. [2.7.1, 2.7.3]
6. Improve user-facing error text instead of returning raw `str(exc)` in
   operator-facing flows. [2.15.2]

### Phase 2 — Structural improvements

1. Add `reload_manifest` and a shutdown guard for registration. [2.4.3, 2.4.4]
2. Add inflight-request drain on graceful shutdown. [2.13.3]
3. Add a basic rate limiter or explicitly require one upstream. [2.12.3]
4. Add metrics around downstream tool calls and service health transitions.
   [2.10.3]
5. Expand the mock MCP server to cover malformed/timeout/error cases and add
   the corresponding integration tests. [2.11.3]

### Phase 3 — Strategic

1. Add OpenTelemetry-style tracing. [2.10.4]
2. Cache the rendered system prompt across rebuilds. [2.14.2]
3. Reduce large tool-result memory spikes by reworking truncation. [2.14.3]
4. Decide whether the main CLI should gain a generic interactive mode. [2.15.3]
5. Add a short downstream-service authoring guide. [2.15.1]

---

## 4. Open questions still worth deciding

1. **Configuration ownership** — should `app/settings.py` be deleted outright,
   or is there a reason to keep it as a compatibility wrapper?
2. **Service visibility semantics** — should startup manifest failures be shown
   in `list_services` the same way runtime registration failures are?
3. **Manifest operations** — is runtime manifest reload in scope, or is restart
   the intended operational model?
4. **Rate limiting location** — should the limiter live in-process, at the MCP
   boundary, or be delegated to an upstream gateway?
5. **CLI scope** — should the main CLI remain a one-shot client with JSON/text
   modes only, or should it absorb a generic REPL mode?
6. **Dev auth model** — are fixed dev tokens enough, or should local token
   configuration move to a file/env-based mechanism?

---

## 5. What was reviewed

Source modules read end-to-end during the current pass:

- `app/main_mcp.py`, `app/config.py`, `app/settings.py`, `app/request_context.py`
- `app/mcp_server/mcp_server.py`
- `app/agent/agent.py`, `app/agent/events.py`, `app/agent/tool_factory.py`,
  `app/agent/system_prompt.py`
- `app/services/registry.py`, `app/services/pool.py`,
  `app/services/discovery.py`, `app/services/models.py`
- `app/sessions/backend.py`, `app/sessions/store.py`
- `app/auth/auth_service.py`, `app/auth/permissions.py`, `app/auth/token.py`,
  `app/auth/_dev_auth_service.py`
- `app/cli/ask.py`, `app/exceptions/__init__.py`, `app/logger/__init__.py`
- `pyproject.toml`, `services.yml.example`, `README.md`
- `docs/master_specification.md`, `docs/archive/reasoning_stream_spec.md`,
  `docs/archive/reasoning_stream_implementation_plan.md`
- `tests/integration/test_openrouter.py`, `tests/integration/conftest.py`,
  `tests/integration/mock_mcp_server.py`, `tests/code_quality/test_code_quality.py`

Surveys (file/symbol level): all of `tests/unit/`, `tests/integration/`,
`docker/`, `scripts/`.

Not in scope: pydantic-ai internals, `gofr-common` source, the future web UI.
