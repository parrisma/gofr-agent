# gofr-agent Implementation Peer Review

Date: 2026-05-13
Reviewer: GitHub Copilot
Scope: Phases 0-11 implementation of the pydantic-ai MCP Streamable HTTP reasoning agent server, including runtime code, CLI, unit tests, integration tests, README, and services example.

## Executive Summary

The implementation is in good shape for a first complete pass. The repository now has a coherent package layout, strong unit/integration coverage, a working FastMCP server surface, a typed service registry, a session store, a pydantic-ai agent wrapper, CLI coverage, and documentation. The current quality gate is green:

```text
ruff: all checks passed
pytest: 131 passed, 44 warnings
```

However, I would not treat this as production-ready yet. The largest concerns are around auth not being enforced at the MCP transport, session-pool checkout semantics under concurrency, dynamic service replacement failure modes, and a `refresh_services` tool that does not actually refresh downstream tool discovery. These issues are fixable without reworking the overall design.

## Strengths

- Clear separation of concerns across config, service discovery, pooling, registry, agent, MCP server, CLI, and session storage.
- Tests cover the core behavior at multiple layers: model/config, registry, pool, agent, MCP server tools, CLI, and live in-process MCP integration.
- The implementation correctly handles the current `mcp` Streamable HTTP API shape by opening a transport and then a `ClientSession`.
- The pydantic-ai `UsageLimits(tool_calls_limit=...)` usage is correct for limiting tool-call iterations.
- The services manifest model and example are understandable and should be easy for operators to adapt.
- Partial degradation during startup is useful: failed services are skipped instead of blocking the whole server.

## Findings

### 1. High: Auth configuration is validated but not enforced by the MCP server

Files:

- `app/config.py:35-53`
- `app/main_mcp.py:90-97`
- `app/mcp_server/mcp_server.py:41-44`
- `app/auth/__init__.py:11-21`

`GofrAgentConfig` requires a JWT secret when `require_auth=True`, and `main_mcp.py` passes `require_auth`/`jwt_secret` into the config. But `create_mcp_server()` creates `FastMCP(...)` without any auth settings, token verifier, middleware, or explicit request validation. The auth module only re-exports gofr-common helpers and is not used by the server path.

Impact:

- A production server started without `--no-auth` will require `GOFR_AGENT_JWT_SECRET`, but requests to `/mcp` still appear unauthenticated at the FastMCP layer.
- The README describes JWT auth behavior that the runtime does not currently enforce.

Recommendation:

- Wire auth into FastMCP using the supported `auth=` or `token_verifier=` path for this MCP version, or wrap the ASGI app with gofr-common auth middleware before passing it to uvicorn.
- Add integration tests that verify unauthenticated requests fail when `require_auth=True` and succeed with a valid token.
- Decide whether downstream service auth and front-door auth use separate tokens and document that boundary.

### 2. High: `SessionPool.checkout()` can hand out the same `ClientSession` to concurrent callers

Files:

- `app/services/pool.py:40`
- `app/services/pool.py:77-92`

The pool has a semaphore sized to `pool_size`, but `_find_live_slot()` returns the first non-`None` slot without marking it as checked out or removing it from availability. If several coroutines call `checkout()` concurrently, they can all receive the same first live `ClientSession`, even when other slots exist.

Impact:

- The pool does not actually provide isolated per-slot usage under concurrency.
- If `ClientSession` is not safe for concurrent `call_tool()` calls, downstream calls can interleave or fail unexpectedly.
- Integration tests currently prove concurrent calls complete, but they do not prove that distinct pool slots are used.

Recommendation:

- Replace the scan-based allocation with an `asyncio.Queue[int]` or `asyncio.Queue[ClientSession]` of available live slots.
- On checkout, pop one slot from the queue; on exit, return it only if it is still healthy.
- Add a test that three concurrent checkouts receive three distinct mocked sessions when `pool_size=3`.

### 3. High: Replacing a registered service is not atomic and can leave stale stopped state

Files:

- `app/services/registry.py:47-56`
- `app/services/registry.py:99-104`

`register_service()` stops the existing pool before trying to open/discover the replacement. If the new connection or tool discovery fails, the old service has already been stopped, while old entries in `_pools`, `_services`, and `_tools` may remain until overwritten. In the failure case, the registry can expose stale tools tied to a stopped pool.

Impact:

- Runtime service updates can degrade a previously healthy service even when the replacement registration fails.
- `list_services` and the agent prompt may still show old tools for a pool that can no longer serve calls.

Recommendation:

- Build and discover the replacement pool in temporary local variables first.
- Only after discovery succeeds, acquire the registry lock, swap in the new service, then stop the old pool.
- If discovery fails, close the new temporary pool and leave the existing registration intact.
- Add a regression test for failed replacement preserving the old healthy pool and tool list.

### 4. Medium: `refresh_services` does not actually rediscover downstream tools

Files:

- `app/mcp_server/mcp_server.py:152-163`
- `app/services/registry.py:84-90`

The MCP tool name and docstring say `refresh_services` should re-discover tools. The implementation only counts existing tools and calls `agent.rebuild()`. If a downstream service adds/removes tools, `refresh_services` will not detect that change.

Impact:

- Clients may believe the agent refreshed tool discovery when it did not.
- The agent can keep stale tool metadata until restart or manual re-registration.

Recommendation:

- Add a `ServiceRegistry.refresh_services()` method that iterates over stored `ServiceConfig` values, re-runs discovery against existing or rebuilt pools, updates `_tools`, and handles per-service failure independently.
- Make the MCP tool call that method and return actual refreshed counts/status.
- Add an integration or unit test where discovery results change after refresh.

### 5. Medium: Agent step reporting API is present but not implemented

Files:

- `app/agent/agent.py:27`
- `app/agent/agent.py:87-96`
- `app/agent/agent.py:105-129`
- `app/mcp_server/mcp_server.py:101-108`

`AgentResult.steps` and the `on_step` callback are exposed as part of the agent API and returned by the MCP `ask` tool, but `steps` remains an empty list and `on_step` is never called. The docstring says the callback is called for tool-call/result events.

Impact:

- Consumers cannot inspect tool-use traces despite the API implying they can.
- Tests may miss regressions in multi-step reasoning behavior because step capture is effectively stubbed out.

Recommendation:

- Either implement event capture from pydantic-ai run events/tool calls or remove the public `steps`/`on_step` surface until it is supported.
- Add tests that verify tool-call steps are recorded when the model calls a tool.

### 6. Medium: Reconnect task scheduling can multiply background tasks on repeated failures

Files:

- `app/services/pool.py:130-140`
- `app/services/pool.py:145-155`

`_open_slot()` schedules a `_reconnect_loop()` whenever opening a slot fails. `_reconnect_loop()` calls `_open_slot()` again. If that retry fails, `_open_slot()` schedules another reconnect task while the current reconnect loop continues. Under a persistently failing service this can create overlapping reconnect loops for the same slot.

Impact:

- Reconnect load can grow over time against an unhealthy downstream service.
- Shutdown must cancel more tasks than expected.

Recommendation:

- Separate a single-attempt `_open_slot_once()` from the scheduling logic.
- Ensure only one reconnect task per slot can exist at a time.
- Remove completed tasks from `_reconnect_tasks` or track them by slot index.

### 7. Medium: CLI auth option is a no-op and there is no token path

Files:

- `app/cli/ask.py:33-37`
- `app/cli/ask.py:45-66`

The CLI exposes `--no-auth`, but `_run()` does not accept or use it. There is also no `--token`, `--token-env`, or Authorization header support.

Impact:

- Once server-side auth is enforced, the CLI will not be able to call an authenticated server.
- The `--no-auth` flag currently suggests behavior that does not exist.

Recommendation:

- Add `--token` and/or `GOFR_AGENT_TOKEN` support and pass headers to `streamablehttp_client`.
- Remove `--no-auth` unless it has a client-side effect.
- Add CLI tests that assert headers are passed when a token is configured.

### 8. Low/Medium: Background lifecycle cleanup is incomplete

Files:

- `app/sessions/store.py:37`
- `app/sessions/store.py:96-102`
- `tests/integration/mock_mcp_server.py:57-65`
- `tests/integration/test_mcp_server_integration.py:37-44`

`SessionStore.start_ttl_sweep()` starts a background task but exposes no stop/cancel method. The full test suite passes but emits a pending-task error from the integration server stack after completion:

```text
ERROR Task was destroyed but it is pending!
coro=<_shutdown_watcher() ... sse_starlette/sse.py:136>
```

The integration helpers also monkey-patch `uvicorn.Server.startup` to detect readiness. This works against the current uvicorn version, but it is a private-ish lifecycle hook and already required adjustment during implementation.

Impact:

- Production shutdown can leave background tasks running until event-loop teardown.
- Test output contains noisy shutdown errors despite passing tests.
- Future uvicorn changes may break the fixtures again.

Recommendation:

- Add `SessionStore.stop_ttl_sweep()` and call it during server shutdown.
- Make test server helpers assert the thread actually exits after `join(timeout=5)`.
- Prefer a supported ASGI test/lifespan harness or readiness polling over monkey-patching uvicorn internals.

### 9. Low: Tool factory silently drops non-text MCP content

Files:

- `app/agent/tool_factory.py:37-47`

`make_tool()` only includes `TextContent` and silently ignores images, resources, audio, and links.

Impact:

- A valid downstream tool can return useful non-text content and the agent sees an empty string.
- Failures are hard to diagnose because ignored content is not reported.

Recommendation:

- Decide the intended content policy: either reject non-text with a clear placeholder/diagnostic, or serialize selected metadata for supported non-text content types.
- Add tests for mixed text/non-text content.

## Test Coverage Notes

Current coverage breadth is strong, but the following gaps map directly to the findings above:

- Authenticated MCP requests, including negative unauthenticated cases.
- Distinct session allocation in `SessionPool` under concurrent checkout.
- Failed dynamic service replacement preserving old state.
- Real `refresh_services` rediscovery behavior.
- Agent step capture/tool-call trace behavior.
- CLI Authorization header behavior.
- Shutdown cleanup with no pending task diagnostics.

## Suggested Remediation Order

1. Enforce server-side auth and add auth integration tests.
2. Fix `SessionPool` checkout allocation and reconnect task scheduling.
3. Make registry service replacement atomic.
4. Implement real service refresh/re-discovery.
5. Decide whether to implement or remove agent step reporting.
6. Add CLI token support.
7. Clean up background lifecycle and integration fixture shutdown noise.
8. Improve non-text tool-result handling.

## Overall Assessment

The architecture is sound and the code is testable. The biggest remaining work is not architectural redesign; it is tightening runtime contracts so the implementation behavior matches the documented API: authenticated means authenticated, a pool means distinct checkout slots, refresh means rediscovery, and returned step traces mean actual step traces. Once those are addressed, this will be much closer to a reliable production-ready MCP orchestration service.
