# Reasoning Stream Implementation Plan

Status: COMPLETED (implemented and validated on 2026-05-15).
Spec: `docs/reasoning_stream_spec.md`
Review basis: `docs/peer_review.md`
Downstream consumer doc that MUST be kept in sync: `docs/react_integration_guide.md`

## Purpose

Implement the approved reasoning-stream design so gofr-agent exposes complex
agent reasoning from day one: live MCP notifications, derived final steps,
request correlation, safer tool-result handling, bounded session memory,
controlled model overrides, constrained production service registration, and
structured observability on the reasoning path.

This plan is intentionally incremental. Each phase should leave the project in
a passing, reviewable state.

## Execution Rules

1. Do not start implementation until this plan is approved.
2. Use `./scripts/run_tests.sh` for test runs; do not use raw `pytest` as the
   final validation command.
3. Run targeted tests during phases when useful, then the full test script before
   marking the plan done.
4. Keep changes scoped to the phase being executed.
5. If an installed library API differs materially from the spec assumptions,
   stop and update this plan before continuing.
6. Do not commit unless explicitly asked.

## Operating Instructions for the Implementing Agent

This plan assumes the implementer may be a weaker model. Therefore each phase
must be executed mechanically and conservatively.

1. **Read before editing.** Before changing a module, read the relevant source
   file and its closest unit/integration tests.
2. **Do not skip checkpoints.** Each phase has design, test, and quality
   checkpoints. Stop when a checkpoint fails; do not continue into later phases.
3. **Prefer additive seams.** Add small helpers/classes before replacing working
   behaviour. Keep old behaviour passing until the replacement is verified.
4. **One behavioural concern at a time.** Do not mix unrelated refactors into a
   phase. For example, do not change session storage while implementing model
   override policy.
5. **Tests first where practical.** For validation, event models, policy checks,
   and retry classification, write or update tests before implementation.
6. **No speculative APIs.** Confirm library APIs in Phase 0 before using them.
   If documentation or introspection disagrees with this plan, update the plan
   and ask for approval.
7. **No hidden failures.** If a test fails, record command, failure summary,
   suspected cause, and whether it is pre-existing. Do not mark a phase done
   with unexplained failures.
8. **Keep final response compatibility.** Unless a phase explicitly changes the
   contract, existing `ask` clients must still receive a final answer.
9. **Do not touch unrelated working-tree state.** Do not delete or modify files
   that the current phase does not own. If unrelated changes appear in `git
   status`, leave them alone and continue.
10. **Pick one name and stick to it.** Where this plan offers alternatives such
    as `app/observability.py` or `app/request_context.py`, choose one in Phase 3
    and use that name everywhere. Do not create both.
11. **Rollback discipline.** If a phase fails partway, revert in-phase code
    changes to the last green state before retrying. Do not leave partially
    implemented behaviour merged into other phases.
12. **Quality gate first.** When in doubt, run `./scripts/run_tests.sh
    --quality` before any other test command in a phase.

## Phase Checkpoint Template

At the end of every phase, update the relevant row in the Validation Log with:

| Required field | Meaning |
|----------------|---------|
| `Phase` | Phase number and name |
| `Design checkpoint` | Short statement confirming the design still matches the spec |
| `Commands` | Exact `./scripts/run_tests.sh ...` commands run |
| `Result` | PASS / FAIL |
| `Notes` | Failures, deviations, or follow-up work |

Do not proceed to the next phase unless:

1. the phase exit criteria are met;
2. targeted tests for the phase pass;
3. `./scripts/run_tests.sh --quality` passes;
4. any skipped or failing tests are explicitly documented and approved.

## Required Test Commands by Scope

Use these commands unless a phase lists a more specific path.

| Scope | Command |
|-------|---------|
| Quality gate | `./scripts/run_tests.sh --quality` |
| Unit tests | `./scripts/run_tests.sh --unit` |
| Integration tests | `./scripts/run_tests.sh --integration` |
| Specific test file | `./scripts/run_tests.sh tests/unit/test_example.py` |
| Keyword run | `./scripts/run_tests.sh -k "keyword"` |
| Full suite | `./scripts/run_tests.sh` |

Full suite is mandatory at the end of the whole implementation. Phase-level
targeted tests plus quality gate are mandatory before moving to the next phase.

## Design Tracking Checklist

Maintain this checklist as phases complete.

| Design invariant | Owner phase | Status |
|------------------|-------------|--------|
| One event source feeds notifications and final `steps` | Phase 2 / 5 | DONE |
| Every `ask` has a `request_id` in logs, events, response | Phase 3 / 5 | DONE |
| Raw tool output never re-enters model context unmarked | Phase 4 | DONE |
| Transient tool failures retry; permanent failures do not | Phase 4 | DONE |
| `AgentResult.steps` is non-empty for tool-using runs | Phase 5 | DONE |
| Session history is bounded and summary-backed | Phase 6 | DONE |
| Model override is activity-gated and allow-listed | Phase 7 | DONE |
| Production dynamic registration is allow-listed | Phase 7 | DONE |
| CLI supports streaming plus quiet/json modes | Phase 8 | DONE |
| README/SPEC match implemented behaviour | Phase 9 | DONE |
| `docs/react_integration_guide.md` matches new MCP notification contract | Phase 9 | DONE |

Update only the status values (`TODO`, `IN PROGRESS`, `DONE`, `BLOCKED`) during
execution; do not rewrite the invariant text without approval.

## Phase 0 - API reconnaissance and baseline

Goal: verify the installed library APIs before touching design-sensitive code.

Tasks:

1. Inspect installed FastMCP / MCP APIs for server-side notifications.
   - Confirm whether `Context` supports `report_progress`, log messages,
     generic notifications, or another supported notification path.
   - Record the exact API chosen in this document before implementation.
2. Inspect installed pydantic-ai APIs for `Agent.iter(...)`.
   - Confirm node/event types available for model streaming, tool calls, tool
     results, and completion.
   - Confirm how to access final result, token usage, and new messages.
3. Inspect `gofr_common` logging APIs.
   - Confirm `StructuredLogger` import path and expected call style.
   - Confirm whether request context helpers already exist.
4. Inspect the MCP client notification surface that the React guide depends on.
   - Confirm the notification names, payload shape, and subscription mechanism
     a TypeScript MCP client would use to receive reasoning events.
   - Record findings; the React guide update in Phase 9 must match.
5. Run the current baseline test script.
   - Command: `./scripts/run_tests.sh`
   - If it fails, capture failures and decide whether they are pre-existing or
     blocking.

Deliverables:

- Notes added to this plan under "Confirmed APIs".
- Baseline test result recorded under "Validation Log".

Exit criteria:

- Notification API, agent iteration API, and structured logger API are known.
- Any baseline failures are understood before code changes begin.

Required checkpoint:

1. Update the Confirmed APIs table with concrete import paths and method names.
2. Update Validation Log with baseline `./scripts/run_tests.sh` result.
3. STOP if FastMCP cannot send notifications or pydantic-ai lacks an iteration
   API capable of exposing tool activity; revise the spec/plan before coding.

## Phase 1 - Configuration, permissions, and validation foundation

Goal: add the policy and safety settings required by later phases without
changing the agent loop yet.

Files likely touched:

- `app/config.py`
- `app/settings.py` (remove or rationalise)
- `app/auth/permissions.py`
- `app/mcp_server/mcp_server.py`
- `tests/unit/test_config.py`
- `tests/unit/test_auth_permissions.py`
- `tests/unit/test_mcp_server.py`
- `tests/code_quality/test_code_quality.py`

Tasks:

1. Rationalise configuration to one path.
   - Prefer `GofrAgentConfig` in `app/config.py` as the single project config.
   - Remove or clearly deprecate `app/settings.py` if unused.
2. Add config fields with safe defaults:
   - `agent_timeout_seconds`
   - `max_steps_hard_cap`
   - `max_question_chars`
   - `max_context_chars`
   - `max_event_payload_chars`
   - `max_response_steps`
   - `max_sessions`
   - `max_messages_per_session`
   - `session_sweep_interval_seconds`
   - `tool_retry_attempts`
   - `dynamic_registration_enabled`
   - `allowed_service_hosts`
   - `allowed_models`
3. Add `AGENT_MODEL_OVERRIDE` permission.
4. Add ask-boundary validation:
   - non-empty question;
   - question length cap;
   - context length cap;
   - `1 <= max_steps <= max_steps_hard_cap`.
5. Add model-override validation shape at the boundary, even if the agent still
   uses the default model until later phases.
6. Add code-quality guard to prevent new stdlib `logging.getLogger(...)` usage
   in modules migrated by Phase 3.

Tests:

1. Config env parsing for each new field.
2. Permission constant exists and is exported where expected.
3. Ask validation accepts valid inputs and rejects invalid lengths / max steps.
4. Model override rejects callers without the new activity.
5. Model override rejects models not in `allowed_models`.

Exit criteria:

- New settings parse from env and have documented defaults.
- `ask` rejects unsafe input before agent execution.
- Permission model supports controlled model override.

Required checkpoint:

1. Run `./scripts/run_tests.sh --quality`.
2. Run `./scripts/run_tests.sh tests/unit/test_config.py tests/unit/test_auth_permissions.py tests/unit/test_mcp_server.py`.
3. Confirm no agent-loop behaviour changed in this phase.
4. Update Design Tracking Checklist if config/permission invariants are done.

## Phase 2 - Event model and collector

Goal: define one event source of truth used by live notifications and final
`AgentResult.steps`.

Files likely touched:

- `app/agent/events.py` (new)
- `app/agent/__init__.py`
- `tests/unit/test_agent_events.py` (new)

Tasks:

1. Add pydantic event models for:
   - `run_started`
   - `step_started`
   - `text_delta`
   - `tool_call`
   - `tool_retry`
   - `tool_result`
   - `summary_update`
   - `step_completed`
   - `run_completed`
   - `run_failed`
2. Add shared fields:
   - `request_id`
   - `session_id`
   - `event_id`
   - `sequence`
   - `kind`
   - `timestamp`
3. Add an `EventCollector` or equivalent small helper that:
   - assigns monotonic sequence numbers;
   - stores bounded events for final `steps`;
   - applies payload truncation limits;
   - builds final derived `steps`.
4. Add a text-delta coalescer with a configurable ~50 ms target window.

Tests:

1. Each event serialises to a plain dict / JSON-compatible structure.
2. Sequence numbers are monotonic.
3. Final steps are derived from collected events.
4. Payloads truncate and set `truncated: true`.
5. Text-delta coalescing preserves text order.

Exit criteria:

- Event schema is stable and covered by unit tests.
- Final steps can be built without the agent loop.

Required checkpoint:

1. Run `./scripts/run_tests.sh --quality`.
2. Run `./scripts/run_tests.sh tests/unit/test_agent_events.py`.
3. Confirm event models are JSON-serialisable plain values only.
4. Confirm final `steps` are derived from collected events, not separately
   hand-built.

## Phase 3 - Structured logging and request correlation on reasoning path

Goal: make logs, audit events, reasoning events, and final responses share one
request id.

Files likely touched:

- `app/request_context.py` (new; chosen name - do not also create
  `app/observability.py`)
- `app/main_mcp.py`
- `app/mcp_server/mcp_server.py`
- `app/agent/agent.py`
- `app/agent/tool_factory.py`
- `app/services/pool.py`
- `app/services/registry.py`
- `app/sessions/store.py`
- `tests/unit/test_request_context.py` (new)
- `tests/code_quality/test_code_quality.py`

Tasks:

1. Add request context helpers using `contextvars`.
2. Generate a `request_id` at the `ask` boundary.
3. Include request id in final `ask` response.
4. Migrate reasoning-path modules to `gofr_common` `StructuredLogger`:
   - `app/main_mcp.py`
   - `app/mcp_server/mcp_server.py`
   - `app/agent/agent.py`
   - `app/agent/tool_factory.py`
   - `app/services/pool.py`
   - `app/services/registry.py`
   - `app/sessions/store.py`
5. Emit structured audit events for guarded MCP calls:
   - request id;
   - activity;
   - session id where available;
   - outcome;
   - error class on failure.
6. Tighten code-quality checks for migrated modules.

Tests:

1. Request context stores and resets request id correctly.
2. `ask` response includes request id.
3. Audit events are emitted for successful and failed guarded calls.
4. Code-quality test rejects stdlib logging in migrated modules.

Exit criteria:

- Reasoning-path logs and responses share a request id.
- New stdlib logging is blocked in migrated modules.

Required checkpoint:

1. Run `./scripts/run_tests.sh --quality`.
2. Run `./scripts/run_tests.sh tests/unit/test_request_context.py tests/unit/test_mcp_server.py`.
3. Confirm every migrated reasoning-path module has no stdlib
   `logging.getLogger(...)`, no top-level `import logging`, and no
   `logging.LoggerAdapter` usage.
4. Confirm request context is reset after each request to avoid leaking ids
   across tests or concurrent requests.
5. Confirm a chosen name for the request-context module exists and the
   alternative name does NOT exist (`ls app/observability.py` returns no file).

## Phase 4 - Tool result safety and structured downstream errors

Goal: stop feeding raw downstream output to the model and make tool failures
recoverable and observable.

Files likely touched:

- `app/exceptions/__init__.py`
- `app/agent/tool_factory.py`
- `app/agent/system_prompt.py`
- `app/agent/events.py`
- `tests/unit/test_tool_factory.py`
- `tests/unit/test_system_prompt.py`
- `tests/integration/mock_mcp_server.py`

Tasks:

1. Add `DownstreamToolError` with:
   - `service`
   - `tool`
   - `message`
   - `transient`
   - `fatal`
   - optional `recovery_hint`
2. Add failure classification for:
   - transient transport / timeout / 5xx-like failures;
   - permanent auth / validation / unknown-tool / policy failures;
   - malformed response failures.
3. Add bounded retry around downstream tool calls.
   - Default total attempts from `tool_retry_attempts`.
   - Never retry permanent failures.
4. Wrap successful tool results with explicit provenance and sentinels before
   re-entering the model context.
5. Wrap failed tool results as structured tool errors before model re-entry.
6. Update the system prompt to instruct the model that tool result blocks are
   untrusted data and not instructions.
7. Emit event collector records for attempts, retries, success, and failure.

Tests:

1. Successful tool result is provenance-wrapped.
2. Prompt-injection-like tool output remains inside data sentinels.
3. Transient failure retries up to configured limit.
4. Permanent failure does not retry.
5. Final failed tool result is structured and marked `ok=false`.
6. System prompt contains tool-output safety instruction.

Exit criteria:

- Raw tool output no longer enters model context unmarked.
- Tool failures are structured and retry behaviour is deterministic.

Required checkpoint:

1. Run `./scripts/run_tests.sh --quality`.
2. Run `./scripts/run_tests.sh tests/unit/test_tool_factory.py tests/unit/test_system_prompt.py`.
3. Run `./scripts/run_tests.sh tests/integration/test_mock_mcp_server.py` if the
   mock server changed.
4. Confirm prompt-injection strings in fake tool output remain inside tool-data
   sentinels in tests.
5. Confirm retries are bounded and permanent failures do not retry.

## Phase 5 - Agent.iter reasoning loop and MCP notifications

Goal: replace the current text-only internal stream with the live reasoning
stream promised by the spec.

Files likely touched:

- `app/agent/agent.py`
- `app/agent/events.py`
- `app/mcp_server/mcp_server.py`
- `tests/unit/test_agent.py`
- `tests/integration/test_mcp_server_integration.py`
- `tests/integration/test_openrouter.py`

Tasks:

1. Refactor `GofrAgent.run()` around pydantic-ai `Agent.iter(...)`.
2. Remove the unused `on_step` callback.
3. Add an event sink abstraction that can:
   - collect events for final steps;
   - send MCP notifications when a FastMCP context is available;
   - operate in tests without MCP context.
4. Send live notifications from the `ask` tool using the confirmed FastMCP API.
5. Emit events for:
   - run start;
   - model text deltas;
   - tool calls;
   - tool retries;
   - tool results;
   - final answer;
   - run completion/failure.
6. Wrap the full run in `asyncio.timeout(config.agent_timeout_seconds)`.
7. Populate final `AgentResult.steps` from the event collector.
8. Preserve existing answer/session/model/tokens fields.

Tests:

1. Unit tests for timeout path.
2. Unit tests that a tool-using run produces non-empty steps.
3. Integration test that MCP client receives notifications in order.
4. Integration test that final steps match emitted notification events.
5. OpenRouter live tests assert at least one `tool_call` and final answer event
   when `OPENROUTER_API_KEY` is set.

Exit criteria:

- `ask` emits live reasoning notifications.
- Final response includes request id and derived non-empty steps for tool runs.
- Existing non-streaming clients still receive a final answer.

Required checkpoint:

1. Run `./scripts/run_tests.sh --quality`.
2. Run `./scripts/run_tests.sh tests/unit/test_agent.py tests/unit/test_mcp_server.py`.
3. Run `./scripts/run_tests.sh tests/integration/test_mcp_server_integration.py`.
4. If `OPENROUTER_API_KEY` is set, run `./scripts/run_tests.sh tests/integration/test_openrouter.py -m openrouter`.
5. Confirm one tool-using integration test has both live notifications and final
   derived steps from the same event sequence.
6. STOP if implementing `Agent.iter(...)` requires a broad rewrite outside
   `app/agent` and `app/mcp_server`; update the plan first.

## Phase 6 - Session backend abstraction and rolling summary

Goal: bound session growth while preserving useful long-context continuity.

Files likely touched:

- `app/sessions/store.py`
- `app/sessions/backend.py` (new)
- `app/agent/agent.py`
- `app/agent/events.py`
- `app/config.py`
- `tests/unit/test_session_store.py`
- `tests/unit/test_agent.py`

Tasks:

1. Introduce a minimal async `SessionBackend` abstraction.
2. Keep the existing in-memory implementation as the default backend.
3. Add session fields / backend state for:
   - `messages`
   - `summary`
   - `created_at`
   - `updated_at`
4. Enforce:
   - `max_sessions`
   - `max_messages_per_session`
   - `session_sweep_interval_seconds`
5. Add summary compaction trigger when configured thresholds are exceeded.
6. Generate rolling summaries that preserve:
   - goals;
   - constraints;
   - decisions;
   - open tasks;
   - important tool findings;
   - user preferences;
   - unresolved errors.
7. Include rolling summary in future agent runs as derived context, not as
   system or user instruction.
8. Emit `summary_update` events when compaction occurs.

Tests:

1. In-memory backend preserves existing session behaviour.
2. Session count cap rejects new sessions clearly.
3. Message cap compacts old messages into summary.
4. Recent window remains intact after compaction.
5. Summary update emits an event.
6. Reset session clears messages and summary.

Exit criteria:

- Session memory is bounded.
- Long sessions keep a rolling summary plus recent raw context.
- Backend abstraction exists without adding external storage.

Required checkpoint:

1. Run `./scripts/run_tests.sh --quality`.
2. Run `./scripts/run_tests.sh tests/unit/test_session_store.py tests/unit/test_agent.py`.
3. Confirm no Redis/Postgres/file persistence dependency was added.
4. Confirm reset clears both raw messages and summary.
5. Confirm summary text is inserted as derived context, not as a system message
   or trusted user instruction.

## Phase 7 - Model override and service registration policy

Goal: implement the approved security policy for model selection and dynamic
service registration.

Files likely touched:

- `app/config.py`
- `app/auth/permissions.py`
- `app/mcp_server/mcp_server.py`
- `app/services/registry.py`
- `app/services/discovery.py`
- `tests/unit/test_config.py`
- `tests/unit/test_auth_permissions.py`
- `tests/unit/test_mcp_server.py`
- `tests/unit/test_registry.py`
- `tests/integration/test_registry_integration.py`

Tasks:

1. Fully wire `model_override` into the `ask` request path.
2. Enforce `AGENT_MODEL_OVERRIDE` before accepting an override.
3. Enforce `allowed_models` before accepting an override.
4. Validate or probe tool capability for override models used in agentic runs.
5. Audit accepted and rejected overrides.
6. Add `dynamic_registration_enabled` enforcement.
7. Add `allowed_service_hosts` matching:
   - exact host names;
   - simple wildcard patterns such as `gofr-*`.
8. Validate dynamic registration policy before opening any pool connection.
9. Probe target service discovery before returning registration success.
10. Represent failed/degraded services clearly in `list_services`.

Tests:

1. Allowed model override succeeds with activity grant.
2. Override without activity fails.
3. Override outside allow-list fails.
4. Dynamic registration disabled fails early.
5. Disallowed host fails and does not enter pool retry.
6. Allowed host probes discovery before success.
7. `list_services` shows failed/degraded state clearly.

Exit criteria:

- Model override is controlled and auditable.
- Production dynamic registration is constrained by policy.

Required checkpoint:

1. Run `./scripts/run_tests.sh --quality`.
2. Run `./scripts/run_tests.sh tests/unit/test_config.py tests/unit/test_auth_permissions.py tests/unit/test_mcp_server.py tests/unit/test_registry.py`.
3. Run `./scripts/run_tests.sh tests/integration/test_registry_integration.py`.
4. Confirm disallowed service hosts never enter the pool retry loop.
5. Confirm rejected model overrides are audited without leaking secrets.

## Phase 8 - CLI streaming consumer

Goal: make the CLI useful for reasoning-stream workflows while preserving simple
answer-only behaviour.

Files likely touched:

- `app/cli/ask.py`
- `tests/unit/test_cli.py`
- `README.md`

Tasks:

1. Add streaming notification consumption using the confirmed MCP client API.
2. Add default compact tree rendering:
   - step start;
   - tool call;
   - tool retry;
   - tool result;
   - final answer.
3. Add `--quiet` for final answer only.
4. Add `--format json` for full event log plus final response.
5. Ensure old simple usage still works.
6. Document CLI modes in README.

Tests:

1. Default mode renders step tree and final answer.
2. `--quiet` renders final answer only.
3. `--format json` emits parseable JSON.
4. CLI handles notification-free servers gracefully.

Exit criteria:

- CLI can demonstrate live reasoning events.
- Existing CLI workflows remain compatible.

Required checkpoint:

1. Run `./scripts/run_tests.sh --quality`.
2. Run `./scripts/run_tests.sh tests/unit/test_cli.py`.
3. Confirm default, `--quiet`, and `--format json` modes have tests.
4. Confirm CLI handles servers that do not emit notifications.

## Phase 9 - Documentation and final validation

Goal: align docs and verify the full system.

Files likely touched:

- `README.md`
- `docs/SPEC.md`
- `docs/reasoning_stream_spec.md`
- `docs/peer_review.md`
- `docs/react_integration_guide.md` (mandatory)
- `services.yml.example` if config examples need updates

Tasks:

1. Update README:
   - reasoning-stream overview;
   - CLI streaming modes;
   - OpenRouter live test instructions;
   - dynamic registration policy;
   - model override policy.
2. Update `docs/SPEC.md` so `ask` documents:
   - MCP notifications as primary stream;
   - final derived steps;
   - request id;
   - model override rules.
3. Ensure `docs/reasoning_stream_spec.md` still matches implemented behaviour.
4. Update `docs/react_integration_guide.md` so it reflects the now-shipped
   reasoning stream. Specifically:
   - Section 1: remove "no live step streaming" from the limitations summary.
   - Section 3 `ask` description: reflect that `steps` is now populated for
     tool-using runs and document the new `request_id` field.
   - Section 4 (Current limitations): rewrite to reflect what is now supported
     vs still deferred (e.g. human-in-the-loop is still deferred).
   - Section 5a (SSE step events): replace with the actual MCP notification
     contract delivered (notification names, payload schema, subscription
     mechanism). Do not invent a separate SSE endpoint.
   - Section 6 reference TypeScript snippets: replace the SSE consumer with a
     working MCP-notification consumer using the confirmed MCP client API.
   - Section 7 phased implementation: collapse Phase 1/Phase 2 into one phase
     since both now work with the shipped server.
   - Add a note that fields, names, and payload shapes match the contract in
     `docs/reasoning_stream_spec.md`.
5. Run targeted tests for all changed areas.
6. Run full validation:
   - `./scripts/run_tests.sh`
7. If `OPENROUTER_API_KEY` is available, run the live OpenRouter integration
   subset through the project test script support or documented invocation.

Exit criteria:

- Docs match implemented behaviour.
- Full test script passes or any failures are documented as pre-existing with
  evidence.

Required checkpoint:

1. Run `./scripts/run_tests.sh --quality`.
2. Run targeted tests for any docs-linked examples if present.
3. Run final full suite: `./scripts/run_tests.sh`.
4. Update Validation Log with the final result.
5. Confirm Design Tracking Checklist contains no `TODO` or `IN PROGRESS` items
   for implemented scope, including the React guide row.
6. Diff `docs/react_integration_guide.md` against `docs/reasoning_stream_spec.md`
   to confirm event names, payload fields, and `ask` response fields match
   exactly. Mismatches fail the phase.

## Suggested Implementation Order

1. Phase 0 - API reconnaissance and baseline.
2. Phase 1 - Configuration, permissions, validation.
3. Phase 2 - Event model and collector.
4. Phase 3 - Structured logging and request correlation.
5. Phase 4 - Tool result safety and structured errors.
6. Phase 5 - Agent.iter loop and MCP notifications.
7. Phase 6 - Session backend and rolling summary.
8. Phase 7 - Model override and service registration policy.
9. Phase 8 - CLI streaming consumer.
10. Phase 9 - Documentation and final validation.

Phases 6 and 7 can be split into separate PR-sized chunks if the changes grow
large. Phase 5 should not begin until Phases 2 and 3 are complete.

## Confirmed APIs

| Area | Confirmed API | Notes |
|------|---------------|-------|
| FastMCP notifications | `mcp.server.fastmcp.Context.request_context.session.send_log_message(...)` | Reasoning events are sent as `notifications/message` log messages with `logger="gofr-agent.reasoning"`, `data=<event>`, and `related_request_id=ctx.request_id`. |
| pydantic-ai iteration | `pydantic_ai.Agent.iter(...)`, `ModelRequestNode`, `CallToolsNode`, `FunctionToolCallEvent`, `FunctionToolResultEvent`, `pydantic_graph.End` | Final output comes from `agent_run.result.output`; history and usage come from `agent_run.new_messages()` and `agent_run.usage()`. |
| StructuredLogger | `gofr_common.logger.StructuredLogger` re-exported through `app.logger.get_logger` | Reasoning-path modules use `get_logger(...)` plus structured keyword fields and request correlation from `app.request_context`. |
| MCP client notifications | `Client.setNotificationHandler("notifications/message", handler)` | Streaming clients subscribe to `notifications/message`, filter `notification.params.logger == "gofr-agent.reasoning"`, and read the event from `notification.params.data`. |

## Validation Log

| Phase | Design checkpoint | Commands | Result | Notes |
|-------|-------------------|----------|--------|-------|
| Phase 0 - Baseline/API | Confirmed FastMCP log notifications, `Agent.iter(...)`, request correlation, and MCP client log-notification handlers match the shipped implementation. | `./scripts/run_tests.sh`; `./scripts/run_tests.sh tests/unit/test_config.py tests/unit/test_auth_permissions.py tests/unit/test_agent_events.py tests/unit/test_request_context.py tests/unit/test_tool_factory.py tests/unit/test_system_prompt.py tests/unit/test_agent.py tests/unit/test_mcp_server.py tests/unit/test_cli.py tests/integration/test_mcp_server_integration.py` | PASS | Original pre-change baseline was not recorded in this document; final suite and focused regression both passed. |
| Phase 1 - Config/permissions/validation | One config path enforces ask-boundary validation and model-override policy before agent execution. | `./scripts/run_tests.sh tests/unit/test_config.py tests/unit/test_auth_permissions.py tests/unit/test_agent_events.py tests/unit/test_request_context.py tests/unit/test_tool_factory.py tests/unit/test_system_prompt.py tests/unit/test_agent.py tests/unit/test_mcp_server.py tests/unit/test_cli.py tests/integration/test_mcp_server_integration.py` | PASS | `test_mcp_server.py` covers question/context/max-steps validation and allow-listed model overrides. |
| Phase 2 - Events/collector | Event models are JSON-safe and final `steps` come from the collector path used for notifications. | `./scripts/run_tests.sh tests/unit/test_config.py tests/unit/test_auth_permissions.py tests/unit/test_agent_events.py tests/unit/test_request_context.py tests/unit/test_tool_factory.py tests/unit/test_system_prompt.py tests/unit/test_agent.py tests/unit/test_mcp_server.py tests/unit/test_cli.py tests/integration/test_mcp_server_integration.py` | PASS | `test_agent_events.py` validates sequence ordering, truncation, and derived steps. |
| Phase 3 - Logging/request id | Reasoning-path logs, notifications, and final `ask` responses share one request id and stdlib logging remains blocked in migrated modules. | `./scripts/run_tests.sh tests/unit/test_config.py tests/unit/test_auth_permissions.py tests/unit/test_agent_events.py tests/unit/test_request_context.py tests/unit/test_tool_factory.py tests/unit/test_system_prompt.py tests/unit/test_agent.py tests/unit/test_mcp_server.py tests/unit/test_cli.py tests/integration/test_mcp_server_integration.py` | PASS | Quality gate enforces migrated logging rules; `test_request_context.py` and `test_mcp_server.py` cover request-id reset and response inclusion. |
| Phase 4 - Tool safety/errors | Tool results re-enter model context only through provenance wrappers, with bounded retries for transient failures. | `./scripts/run_tests.sh tests/unit/test_config.py tests/unit/test_auth_permissions.py tests/unit/test_agent_events.py tests/unit/test_request_context.py tests/unit/test_tool_factory.py tests/unit/test_system_prompt.py tests/unit/test_agent.py tests/unit/test_mcp_server.py tests/unit/test_cli.py tests/integration/test_mcp_server_integration.py` | PASS | `test_tool_factory.py` covers sentinel wrapping, transient/permanent retry handling, and structured failures. |
| Phase 5 - Agent.iter/notifications | Live MCP reasoning notifications and final derived `steps` are emitted from the same event sequence. | `./scripts/run_tests.sh tests/unit/test_config.py tests/unit/test_auth_permissions.py tests/unit/test_agent_events.py tests/unit/test_request_context.py tests/unit/test_tool_factory.py tests/unit/test_system_prompt.py tests/unit/test_agent.py tests/unit/test_mcp_server.py tests/unit/test_cli.py tests/integration/test_mcp_server_integration.py` | PASS | `test_mcp_server_integration.py` asserts notification ordering and equality between notifications and final `steps`. |
| Phase 6 - Session backend/summary | Session memory is bounded, summary-backed, and injected as derived context rather than trusted instructions. | `./scripts/run_tests.sh tests/unit/test_session_store.py tests/unit/test_agent.py tests/unit/test_exceptions.py` | PASS | Added in-memory backend abstraction, session cap enforcement, summary compaction, and `summary_update` events. |
| Phase 7 - Model/service policy | Model override remains activity-gated and allow-listed; runtime service registration is explicitly policy-gated and host allow-listed. | `./scripts/run_tests.sh tests/unit/test_registry.py tests/unit/test_mcp_server.py tests/unit/test_exceptions.py`; `./scripts/run_tests.sh tests/integration/test_registry_integration.py` | PASS | Dynamic registration rejects disallowed hosts before pool creation and records failed service state for `list_services`. |
| Phase 8 - CLI streaming | CLI consumes MCP reasoning notifications in default mode and preserves quiet/json compatibility. | `./scripts/run_tests.sh tests/unit/test_config.py tests/unit/test_auth_permissions.py tests/unit/test_agent_events.py tests/unit/test_request_context.py tests/unit/test_tool_factory.py tests/unit/test_system_prompt.py tests/unit/test_agent.py tests/unit/test_mcp_server.py tests/unit/test_cli.py tests/integration/test_mcp_server_integration.py` | PASS | `test_cli.py` covers default, `--quiet`, `--format json`, and notification-free servers. |
| Phase 9 - Docs/final (incl. `docs/react_integration_guide.md`) | README, core spec, reasoning-stream spec, and React integration guide match the shipped MCP notification contract and final `ask` shape. | `./scripts/run_tests.sh` | PASS | Final suite: 5 quality tests passed, 221 unit tests passed, 115 integration tests passed, 9 OpenRouter tests skipped because `OPENROUTER_API_KEY` was not set. |

When a phase fails, append the failing command and short root-cause note to the
phase row. Do not overwrite failure evidence with a later passing run; preserve
both in the Notes cell.

## Mandatory Quality Review Before Final Completion

Before declaring implementation complete, perform this review pass:

1. Re-read `docs/reasoning_stream_spec.md` and confirm every acceptance
   criterion is implemented or explicitly deferred.
2. Re-read the Design Tracking Checklist and ensure no implemented-scope item is
   `TODO`, `IN PROGRESS`, or `BLOCKED`.
3. Search for raw downstream tool-output concatenation and confirm all model
   re-entry paths use provenance sentinels.
4. Search migrated modules for `logging.getLogger`, `import logging`, and
   `logging.LoggerAdapter` and confirm none remain.
5. Search `ask` responses and event payloads for `request_id` coverage.
6. Confirm final `AgentResult.steps` is generated from the event collector, not
   a duplicate path.
7. Confirm `./scripts/run_tests.sh` passes.
8. Confirm `docs/react_integration_guide.md` no longer contains the obsolete
   "no live step streaming" or separate-SSE-endpoint guidance, and that its
   event names, payload fields, and `ask` response shape match
   `docs/reasoning_stream_spec.md`.

## Deferred Work

1. OpenTelemetry tracing.
2. Redis/Postgres session backend.
3. Full hierarchical or semantic memory.
4. Signed downstream service manifests.
5. Web UI rendering of reasoning streams.
6. Model profile routing by `reasoning_effort`.

## Approval Gate

Implementation should not begin until this plan is approved.
