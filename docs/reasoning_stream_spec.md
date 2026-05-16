# Reasoning Stream Spec

## Purpose

gofr-agent should make complex reasoning observable from day one. A caller
should be able to see the agent's live reasoning flow as it plans, calls tools,
receives results, recovers from failures, compacts long session context, and
produces a final answer.

This spec defines the behaviour and contracts for a live reasoning event stream
for the `ask` workflow. It intentionally avoids implementation details beyond
naming the existing project boundaries that must participate.

## Goals

1. Emit live reasoning events during `ask` runs over MCP notifications.
2. Keep the final `ask` return useful for non-streaming clients by including
   derived `steps` built from the same event sequence.
3. Add request correlation so logs, events, tool calls, and final responses can
   be tied together.
4. Represent downstream tool failures as structured events and structured model
   context, not ordinary text blobs.
5. Support bounded, useful long-conversation memory through a rolling summary
   plus recent raw message window.
6. Keep model override controlled by permission and allow-list.
7. Keep dynamic service registration flexible in development and constrained in
   production.

## Non-goals

1. No OpenTelemetry tracing in the first reasoning-stream implementation.
2. No Redis/Postgres/session persistence backend in the first implementation.
3. No full hierarchical memory or semantic retrieval over session history.
4. No arbitrary user-selected model strings.
5. No signed downstream service manifests yet.
6. No web UI implementation in this spec.

## Current Behaviour

Today, the `ask` tool returns a final response containing `session_id`,
`request_id`, `answer`, `steps`, `model`, and `tokens_used`. The `steps` list is
derived from the same reasoning event sequence emitted during the run and is
non-empty for tool-using runs or summary-compaction runs. Clients receive live
reasoning events through MCP `notifications/message` log messages with logger
`gofr-agent.reasoning`. Downstream tool results are wrapped with explicit data
sentinels before they re-enter model context. Session history is process-local
but bounded through a rolling summary plus recent raw-message window.

## Target Behaviour

When a caller invokes `ask`, gofr-agent creates a request id and emits live MCP
notifications for the run. Notifications represent model progress, tool calls,
tool results, retries, summary updates, and completion. The final MCP response
contains the final answer and a compact `steps` list derived from the same event
sequence.

Streaming-aware clients render events as they arrive. Simple clients can ignore
notifications and use the final response only.

## Service Interaction Diagram

This view matches the interaction shape the reasoning-stream spec describes:
services are laid out horizontally, time flows downward, and result handoff is
shown as agent-mediated calls between participants. The contract still does not
allow direct MCP-to-MCP result passing. gofr-agent receives a result set from
one downstream MCP service, wraps it as bounded untrusted data, and uses that
result to decide the next downstream tool call.

~~~mermaid
sequenceDiagram
   autonumber
   participant Caller
   participant Agent as gofr-agent
   participant Registry as ServiceRegistry
   participant Source as MCP Service A
   participant Next as MCP Service B

   Note over Agent,Registry: Startup
   Agent->>Registry: load configured services
   Registry-->>Agent: manifest discovery status\nready or failed per service

   opt Runtime registration
      Caller->>Agent: register_service(url)
      Agent->>Registry: validate registration policy\nand probe target MCP service
      alt Registration accepted
         Registry-->>Agent: discovered valid manifest
         Agent-->>Caller: registration success
      else Registration rejected
         Registry-->>Agent: disabled disallowed host\nor invalid manifest
         Agent-->>Caller: explicit registration failure
      end
   end

   Caller->>Agent: ask(question, session_id, model_override?)
   Agent-->>Caller: run_started notification\nrequest_id assigned

   Agent->>Source: tool_call(source_tool, args)
   alt Transient source failure
      Source-->>Agent: transient error
      Agent-->>Caller: tool_retry notification
      Agent->>Source: retry source_tool
   end
   Source-->>Agent: tool_result(result set)
   Agent-->>Caller: tool_result notification

   Note over Agent: wrap result with provenance markers\nand payload bounds
   Note over Agent: model treats result as data\nand negotiates next tool call

   Agent->>Next: tool_call(next_tool, args derived from prior result set)
   alt Transient next-service failure
      Next-->>Agent: transient error
      Agent-->>Caller: tool_retry notification
      Agent->>Next: retry next_tool
   end
   Next-->>Agent: tool_result(derived result)
   Agent-->>Caller: tool_result notification

   opt Session compaction
      Agent-->>Caller: summary_update notification
   end

   Agent-->>Caller: run_completed notification
   Agent-->>Caller: final response\nanswer plus derived steps
~~~

## Request Correlation

Every `ask` run has a `request_id`.

The same `request_id` must appear in:

1. every reasoning-stream event;
2. structured logs on the reasoning path;
3. audit events for guarded MCP calls;
4. downstream tool-call logs;
5. the final `ask` response.

The `request_id` is generated by gofr-agent unless a trusted upstream request id
is available through the MCP context. Caller-provided ids must not be trusted as
security boundaries.

## Event Model

Events are typed records. Each event includes at least:

| Field | Description |
|-------|-------------|
| `request_id` | Correlates the full run |
| `session_id` | Conversation session id |
| `event_id` | Unique id within the run |
| `sequence` | Monotonic event sequence number |
| `kind` | Event type |
| `timestamp` | UTC event timestamp |

### Required Event Kinds

| Kind | Purpose |
|------|---------|
| `run_started` | A new `ask` run began |
| `step_started` | A logical model/tool/summary/final step began |
| `text_delta` | Streaming model text fragment |
| `tool_call` | The model requested a downstream tool call |
| `tool_retry` | A transient tool failure will be retried |
| `tool_result` | A downstream tool call completed or failed |
| `summary_update` | Older session history was compacted into the rolling summary |
| `step_completed` | A logical step completed |
| `run_completed` | The run completed successfully |
| `run_failed` | The run failed before producing a final answer |

### Step Kinds

`step_started` uses one of these step kinds:

| Step kind | Meaning |
|-----------|---------|
| `thought` | Model reasoning or answer generation |
| `tool_call` | A downstream tool invocation |
| `tool_result` | Handling a downstream tool result |
| `summary` | Session compaction / summary update |
| `final_answer` | Final answer emission |

### Event Payload Limits

Events must be bounded. Tool arguments, tool summaries, model deltas, and final
step lists must respect configured payload limits. When content is truncated,
the event must include `truncated: true` and enough metadata for debugging.

## MCP Transport Contract

The `ask` tool emits reasoning events as MCP notifications while the run is in
progress.

Concrete transport details:

| Field | Value |
|-------|-------|
| Notification method | `notifications/message` |
| Logger name | `gofr-agent.reasoning` |
| Event payload location | `notification.params.data` |
| Correlation field | `request_id` |

The final return remains synchronous and includes:

| Field | Description |
|-------|-------------|
| `session_id` | Session id used for the run |
| `request_id` | Request id for correlation |
| `answer` | Final answer text |
| `steps` | Derived compact list from the emitted events |
| `model` | Model used for the run |
| `tokens_used` | Total token usage when available |

The notification stream is the primary observability channel. The final `steps`
array exists for compatibility, tests, and simple clients.

## Client Behaviour

The CLI should become a streaming consumer.

Default CLI behaviour:

1. render a compact tree of reasoning steps;
2. render the final answer;
3. show request id when verbose output is enabled.

Additional modes:

| Mode | Behaviour |
|------|-----------|
| `--quiet` | Print only the final answer |
| `--format json` | Print the full event log and final response as JSON |

Clients that do not support notifications can continue to call `ask` and read
only the final response.

## Tool Result Safety

Downstream tool output is untrusted model context. Tool results must be wrapped
with explicit provenance and boundaries before being passed back to the model.
The system prompt must instruct the model to treat tool output as data, not as
instructions.

Tool-result events must identify:

| Field | Description |
|-------|-------------|
| `service` | Downstream service name |
| `tool` | Downstream tool name |
| `ok` | Whether the call succeeded |
| `summary` | Bounded result summary or structured error |
| `truncated` | Whether the result was truncated |
| `latency_ms` | Tool-call latency |
| `attempt` | Attempt number |

## Tool Error Recovery

Downstream tool failures use a structured error shape with:

| Field | Description |
|-------|-------------|
| `service` | Service that failed |
| `tool` | Tool that failed |
| `message` | Safe user-facing error summary |
| `transient` | Whether retry is appropriate |
| `fatal` | Whether the whole `ask` must fail |
| `recovery_hint` | Optional operator/user hint |

Transient failures may retry. Auth failures, validation errors, unknown tools,
policy denials, and malformed requests must not retry. Retry attempts are
bounded and observable through the event stream.

If retries fail and the failure is non-fatal, the model receives a clearly
marked structured tool error and may continue reasoning. Fatal failures end the
run with a clear MCP error and a `run_failed` event.

## Session Memory

Session storage should move behind a small backend abstraction. The first
implementation keeps the in-memory backend as default.

Session state includes:

| Field | Description |
|-------|-------------|
| `session_id` | Session identifier |
| `messages` | Recent raw conversation messages |
| `summary` | Rolling long-term session summary |
| `created_at` | Creation timestamp |
| `updated_at` | Last update timestamp |

Long sessions use a rolling summary plus recent raw window:

1. recent messages remain verbatim up to configured message/token limits;
2. older chunks are compacted into `summary` when thresholds are exceeded;
3. summary updates are emitted as `summary_update` events;
4. summaries preserve goals, constraints, decisions, open tasks, important tool
   findings, user preferences, and unresolved errors;
5. summaries are treated as derived context, not trusted system instructions.

The first implementation must include bounds for maximum sessions, maximum
messages per session, and sweep interval. A persistent backend is a future
implementation behind the same abstraction.

## Model Selection

The default model remains configured at server startup.

Per-request `model_override` is allowed only when:

1. the caller has `AGENT_MODEL_OVERRIDE`;
2. the requested model appears in configured `allowed_models`;
3. the model is suitable for the requested run, including tool-use capability
   for agentic requests.

Every accepted or rejected override is audited with request id, session id,
requested model, selected model, and outcome.

A future model-profile layer can map user-facing profiles such as
`reasoning_effort` to configured models without breaking this contract.

## Dynamic Service Registration

Development mode remains flexible. Production must constrain dynamic service
registration.

`register_service` must respect:

| Config | Purpose |
|--------|---------|
| `dynamic_registration_enabled` | Allows disabling runtime registration |
| `allowed_service_hosts` | Exact or simple-pattern allow-list for target hosts |

A registration succeeds only if:

1. dynamic registration is enabled;
2. the host is allowed by policy when running in production/authenticated mode;
3. the target responds to MCP discovery;
4. the discovered tool manifest is valid;
5. the service can be represented in `list_services` with a clear status.

Denied hosts must fail explicitly and must not enter the service pool retry
loop.

## Logging and Audit

The reasoning path migrates to `gofr_common` `StructuredLogger` first.

Scope for the first pass:

1. `app/main_mcp.py`
2. `app/mcp_server/mcp_server.py`
3. `app/agent/agent.py`
4. `app/agent/tool_factory.py`
5. `app/services/pool.py`
6. `app/services/registry.py`
7. `app/sessions/store.py`

Every guarded MCP tool call emits an audit event with request id, activity,
session id when available, outcome, and error class when failed.

After the hot path is migrated, code-quality checks should prevent new stdlib
`logging.getLogger(...)` usage in migrated modules.

## Configuration

The implementation plan should add or rationalise configuration for:

| Setting | Purpose |
|---------|---------|
| `agent_timeout_seconds` | Wall-clock timeout for a run |
| `max_steps` hard cap | Upper bound for caller-provided `max_steps` |
| `max_question_chars` | Input size bound |
| `max_context_chars` | Context size bound |
| `max_event_payload_chars` | Event payload bound |
| `max_response_steps` | Final response steps bound |
| `max_sessions` | Session count bound |
| `max_messages_per_session` | Recent raw message bound |
| `session_sweep_interval_seconds` | Sweep cadence |
| `tool_retry_attempts` | Bounded retry count |
| `dynamic_registration_enabled` | Runtime registration policy |
| `allowed_service_hosts` | Production registration allow-list |
| `allowed_models` | Model override allow-list |

`app/config.py` and `app/settings.py` must be rationalised so there is one
clear configuration path.

## Validation and Error Semantics

The `ask` boundary validates:

1. question is non-empty and within size limits;
2. context is within size limits;
3. max steps is within server limits;
4. model override policy is satisfied when present.

MCP errors should map to meaningful categories. Validation errors should not be
reported as service failures. Auth errors should not be reported as invalid tool
arguments. Downstream failures should be distinguishable from caller mistakes.

## Testing Requirements

The implementation must add tests at three levels.

### Unit tests

1. event model serialisation;
2. event sequence ordering helpers;
3. text-delta coalescing;
4. tool result truncation and provenance wrapping;
5. structured downstream error classification;
6. session compaction thresholds and summary update behaviour;
7. model override policy;
8. allowed service host policy.

### Integration tests

1. MCP client receives notifications in expected order;
2. final `steps` matches emitted event sequence;
3. mock tool success emits `tool_call` and `tool_result`;
4. mock transient failure retries and then succeeds;
5. mock permanent failure does not retry;
6. dynamic registration denies disallowed hosts in production policy;
7. session summary update appears after compaction threshold.

### Live OpenRouter tests

When `OPENROUTER_API_KEY` is present:

1. a real agentic run emits at least one `tool_call` event;
2. final response includes non-empty derived `steps`;
3. selected default model supports tool use;
4. allowed model override works for an allow-listed tool-capable model.

## Acceptance Criteria

The reasoning-stream work is complete when:

1. `ask` emits live MCP reasoning notifications for model text, tool calls,
   tool results, retries, summary updates, and completion;
2. final `ask` responses include `request_id` and non-empty derived `steps` for
   tool-using runs;
3. downstream tool output is clearly marked as untrusted data before model
   re-entry;
4. transient tool failures retry within configured limits and emit events for
   each attempt;
5. long sessions compact older history into a rolling summary while preserving a
   recent raw window;
6. model overrides are activity-gated and allow-listed;
7. production dynamic registration is constrained by allow-listed hosts;
8. reasoning-path logs use structured logging with request id;
9. the test suite covers event stream, final steps, retry classification,
   compaction, model override, and registration policy;
10. `./scripts/run_tests.sh` passes.

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Notification flood from text deltas | Coalesce deltas on a small time window and cap payloads |
| Event and final steps diverge | Build final steps from the same event collector |
| Tool output prompt injection | Use sentinels/provenance and system-prompt guidance |
| Retry hides outages | Emit every attempt and include retry metadata |
| Summary loses important context | Preserve explicit summary categories and test compaction |
| Model override increases cost | Require activity grant and allow-list |
| Dynamic registration becomes SSRF-like | Use production allow-list and health probe before registration |
| Logging migration grows too wide | Limit first pass to reasoning path |

## Open Items for Implementation Plan

1. Confirm exact FastMCP notification API shape available in the installed MCP
   version.
2. Confirm pydantic-ai `Agent.iter(...)` node/event APIs for the installed
   version.
3. Decide exact event class names and wire field names.
4. Decide hard default values for all new configuration settings.
5. Decide whether summary generation uses the main model or a configured cheaper
   summarisation model.
6. Decide how much of the CLI streaming UX lands in the first implementation
   slice.
