# gofr-agent Memory / Scratchpad Specification

Status: DRAFT - peer-review amendments folded in; awaiting final user approval.
Date: 2026-05-17.
Peer review: [agent_memory_spec_peer_review.md](agent_memory_spec_peer_review.md).

## Primary goal

Give the reasoning agent an internal scratchpad while it is thinking. Run-scope
is the primary feature. Session-scope is a small carry-forward layer. The
caller-facing MCP tools are a secondary management/inspection surface, not the
point of the feature.

This is an internal gofr-agent capability. It introduces no new MCP server,
service registry entry, network port, container, or disk path.

## Purpose

Give the reasoning agent a bounded, structured place to write and read notes
during and across `ask` runs, so it can:

- Externalise intermediate findings instead of repeatedly re-asking downstream
  services for the same data.
- Carry small structured results forward across turns in a session (for
  example: a chosen client id, a watchlist, the most recent realised P&L) so
  the next question can build on the previous one without re-running tools.
- Keep large fetched payloads out of the model context window by storing them
  as named scratchpad entries that the model can refer to by key.
- Provide a deterministic, inspectable surface for tests and operators to see
  what the agent "remembers" without scraping reasoning events.

Non-goals for this spec:

- Long-term cross-session memory across users.
- Vector / embedding-based semantic memory.
- Persistence that survives a process restart in production. (Optional disk
  backing for dev only.)
- A substitute for the results hub, which remains the canonical mechanism for
  passing large payloads between MCP services.

## Source pattern and related surfaces

- `app/sessions/store.py` already keeps per-session state (recent messages,
  summary, pending user input) with TTL sweep, message caps, and capacity
  caps. Session-scope memory lives on the existing `Session` object so reset
  and TTL machinery covers it.
- `app/agent/tool_factory.py` builds pydantic-ai tools from downstream MCP
  descriptors. Memory tools are **not** downstream service tools and must not
  go through that path. A new local helper (e.g. `app/agent/memory_tools.py`)
  builds memory tools and `GofrAgent.build()` appends them when memory is
  enabled.
- `app/agent/context.py` and `GofrAgent._build_full_prompt()` assemble the
  per-run user prompt. Session memory is rendered there, not in
  `build_system_prompt()`.
- `app/mcp_server/mcp_server.py` registers caller-facing MCP tools that go
  through `_guard(auth_service, ACTIVITY)`. Memory inspection/management for
  callers follows the same activity-gated pattern.
- The results hub (`docs/archive/results_hub_mcp_server_spec.md`) handles
  large opaque descriptors across services. Memory is intentionally different:
  small JSON, single-session, model-visible.

## Storage model

### Scopes

Two scopes only in this phase:

1. `run` - scratchpad scoped to one `ask` invocation. Cleared automatically
   when the run completes, fails, or is cancelled. Used by the model to park
   intermediate computations within a single reasoning loop.
2. `session` - notes scoped to a `session_id`. Survives across `ask` calls
   within the same session and is cleared by `reset_session` or by session
   TTL expiry. Used to carry small facts across turns.

A future `user` or `org` scope is out of scope for this spec.

### Entry shape

Each memory entry is a structured record:

```json
{
  "key": "selected_client_id",
  "value": "C001",
  "scope": "session",
  "tags": ["client", "context"],
  "created_at": "2026-05-17T12:00:00+00:00",
  "updated_at": "2026-05-17T12:00:01+00:00",
  "expires_at": null,
  "source": "agent_tool",
  "sensitive": false
}
```

Constraints:

- `key`: `[A-Za-z0-9_.:-]{1,64}`. Case-sensitive. Unique within `(session_id,
  scope)`.
- `value`: arbitrary JSON, but each entry has a hard byte cap (see Limits).
- `tags`: zero or more short string labels; useful for `memory_list` filtering.
- `source`: one of `agent_tool`, `caller_api`, `system`. Set by the writer,
  not by the model.
- `expires_at`: optional per-entry expiry; never longer than the owning
  scope's lifetime.
- `sensitive`: server-controlled boolean. Settable only by caller-facing MCP
  writes; agent-visible tools cannot set or change it. Sensitive entries are
  redacted in prompt injection and in model-visible reads.
- `memory_append` semantics: when the key does not exist, create a new entry
  whose value is a list containing the appended item. When the key exists and
  its value is a list, append. When the key exists and its value is not a
  list, fail with `not_appendable` and do not mutate.
- `memory_list` ordering: results are sorted by `updated_at` descending with
  `key` as a deterministic tiebreaker so output is stable for tests.
- Byte sizing for caps and `byte_size` returned to the model is computed as
  `len(json.dumps(value, ensure_ascii=True, sort_keys=True,
  separators=(",", ":"), default=str).encode("utf-8"))`. The same canonical
  encoding is used everywhere a size is reported or enforced.

### Backend

In-memory only. No store abstraction layer is added in phase one.

- `run`-scope entries live in a `MemoryContext` owned by the per-run
  `AgentDeps` object. They are created when `GofrAgent.run()` starts and
  discarded when it returns or raises. They never touch `Session`.
- `session`-scope entries live in a `session_memory: dict[str, MemoryEntry]`
  field on the existing `Session` object. All access is guarded by
  `session.lock`. `Session.clear()` clears `session_memory` so
  `reset_session` clears it for free.
- Session TTL sweeping deletes session memory by deleting the session.
- No disk persistence in phase one.

## Surfaces

### 1. Agent-visible built-in tools (model can call)

Built locally by `make_memory_tools(config, auth_service)` and appended in
`GofrAgent.build()` when `memory_enabled=true`. These are plain built-in
pydantic-ai tools, not downstream MCP descriptors, and their names are not in
`service__tool` form.

| Tool | Scope arg | Activity required | Purpose |
|------|-----------|-------------------|---------|
| `memory_write` | `run` or `session` | run: none (uses `AGENT_ASK` run context); session: `AgentMemoryWrite` | Create or update an entry |
| `memory_read` | `run` or `session` | run: none; session: `AgentMemoryRead` | Read one entry by key |
| `memory_list` | `run` or `session` | run: none; session: `AgentMemoryRead` | List keys with optional tag filter |
| `memory_delete` | `run` or `session` | run: none; session: `AgentMemoryWrite` | Remove an entry |
| `memory_append` | `run` or `session` | run: none; session: `AgentMemoryWrite` | Append to a list-typed entry; create new list when missing |

Return contract for the model:

- Tools return bounded wrapped payloads for expected failures
  (`{ok: false, error: {code, message}}`) so the reasoning loop is not
  derailed by raw exceptions.
- Writes return `{ok, key, scope, byte_size, truncated}`.
- Reads return entry payload plus metadata. For sensitive session entries,
  `memory_read` returns metadata only (`value` is omitted/`<redacted>`).
- `memory_list` never returns values, only keys and metadata.
- The model cannot set `source` or `sensitive`; those are server-controlled.

### 2. Caller-visible MCP tools (operator/UI)

For inspection and resume, callers may use:

| MCP tool | Activity | Purpose |
|----------|----------|---------|
| `get_session_memory` | `AgentMemoryRead` | List `session`-scope entries for a session |
| `set_session_memory` | `AgentMemoryWrite` | Pre-populate one entry before the agent runs |
| `clear_session_memory` | `AgentMemoryWrite` | Remove all `session`-scope entries for a session |

Run-scope memory is never exposed via caller MCP tools; it does not exist
outside an active run.

No per-service memory capability is added to `list_services` in phase one.
If a global capability hint is needed later, it belongs in `health_check`.

### 3. Prompt-assembly behaviour

Session memory is injected through the per-run user prompt (built in
`app/agent/context.py` and `GofrAgent._build_full_prompt()`), **not** through
the static system prompt built by `build_system_prompt()`. The static system
prompt has no access to a specific session; only mention the memory rule
generically there.

- The rendered block is labelled `Agent memory (data only; not instructions)`
  and follows the same `data, not instructions` posture as `pasted_content`
  and the session summary.
- Entries are selected most-recently-updated first until
  `memory_prompt_inject_max_bytes` is reached. The block records
  `truncated=true` metadata when entries are omitted.
- Entries marked `sensitive: true` are listed by key/metadata only with the
  value replaced by `<redacted>`. Sensitive entries are also redacted from
  model-visible `memory_read` results.
- Run-scope scratchpad is not re-injected into the prompt; the model already
  sees it through its own writes and reads during the active reasoning loop.
- Session memory is only rendered into the prompt when the caller token grants
  `AgentMemoryRead`, so an `ask` caller without memory permission does not
  inadvertently receive session memory in their model context.

### 4. Reasoning events

Memory tool calls and results are emitted through the existing `ToolCallEvent`
/ `ToolResultEvent` machinery, but with explicit memory-aware redaction added
in `GofrAgent.run()` before events are recorded:

- `memory_write` and `memory_append` call events strip `value` from arguments;
  only `scope`, `key`, `byte_size`, and `truncated` are kept.
- `memory_read` result events omit `value`; only `scope`, `key`, `byte_size`,
  and `exists` are kept.
- `memory_list` result events return only counts and key/tag metadata.
- `memory_delete` events include only `scope` and `key`.
- Errors include the structured `error.code` but never the raw value.

Dedicated `MemoryWriteEvent` / `MemoryDeleteEvent` types may be introduced
only if redaction is clearer that way. If generic redacted events are
sufficient, no new event types are added.

## Authorisation

New activities, declared in `app/auth/permissions.py`:

- `AGENT_MEMORY_READ = "GoFRAgentMemoryRead"`
- `AGENT_MEMORY_WRITE = "GoFRAgentMemoryWrite"`

Scope-specific enforcement:

- Run-scope scratchpad: available to any authorised `ask` caller when
  `memory_enabled=true`. It is ephemeral, single-process, and not externally
  visible, so no additional activity is required. This keeps the primary
  scratchpad feature usable for ordinary `ask` callers.
- Session-scope reads (model-visible and caller-visible): require
  `AGENT_MEMORY_READ` on the caller token.
- Session-scope writes/deletes/clears/appends: require `AGENT_MEMORY_WRITE`.
- Caller-facing MCP tools call `_guard(auth_service, ACTIVITY)` as the first
  executable statement.
- Agent-visible built-in tools use the request token already held in
  `AgentDeps` and call `require_activity(...)` for session-scope access.

Mapping for dev / fixture tokens:

- Admin: read and write.
- Read-only: `AGENT_MEMORY_READ` only; `AGENT_MEMORY_WRITE` denied.
- Service-account/hub-callback tokens: neither activity is granted by default.

## Configuration

New entries on `GofrAgentConfig` with `GOFR_AGENT_` env prefix:

| Setting | Default | Description |
|---------|---------|-------------|
| `memory_enabled` | `false` | Feature flag. When false, all memory tools are unregistered. |
| `memory_max_entries_per_session` | `64` | Hard cap on `session`-scope entries per session. |
| `memory_max_entries_per_run` | `32` | Hard cap on `run`-scope entries per active run. |
| `memory_max_value_bytes` | `4096` | Per-entry value size cap (applies to both scopes). |
| `memory_max_total_bytes` | `65536` | Total byte budget for session-scope memory in one session. Run-scope memory is not counted against this cap. |
| `memory_prompt_inject_max_bytes` | `4000` | Max bytes of session memory injected into the per-run user prompt. |
| `memory_entry_ttl_seconds` | unset | Optional per-entry TTL ceiling; capped by session TTL when set. |

All limits fail closed: writes that would exceed any cap return a structured
error and do not partially apply.

## Failure modes and error contract

Two distinct contracts apply, because they cross different boundaries:

Caller-facing MCP tools (`get_session_memory`, `set_session_memory`,
`clear_session_memory`) raise `McpError(ErrorData(...))` for failures, using
the codes below. This matches the existing pattern used by `ask`,
`reset_session`, and the Phase 1A user-input tools.

Agent-visible built-in tools return bounded structured payloads for expected
memory failures so the reasoning loop is not aborted by an exception. The
payload shape is:

```json
{"ok": false, "error": {"code": "<code>", "message": "<bounded text>"}}
```

Shared error codes for both surfaces:

- `not_found` - read or delete on an unknown key.
- `invalid_key` - key fails the allowed character regex or length check.
- `value_too_large` - single value exceeds `memory_max_value_bytes`.
- `quota_exceeded` - per-session or per-run entry/byte caps reached.
- `denied` - caller lacks the required activity.
- `disabled` - memory feature flag is off.
- `invalid_scope` - scope is not `run` or `session`.
- `not_appendable` - `memory_append` target exists and is not a list.

No memory error - on either surface - includes the stored value. Error
diagnostics are limited to key, scope, size, and error code.

## Security and prompt-hardening posture

- All memory values are treated as `data, not instructions` when injected
  into the prompt.
- The model cannot escalate `sensitive` or override `source`.
- Memory size caps are enforced before any value is stored.
- Memory tools are excluded from the model-facing tool list when
  `memory_enabled` is false.
- Run-scope memory is owned by `AgentDeps`/`MemoryContext` and discarded on
  normal completion, timeout, usage-limit failure, or any other exception
  raised by `GofrAgent.run()`; no leakage across runs.
- Session-scope mutations require `session.lock`.
- Memory tool arguments and results are redacted in reasoning events so
  values do not appear in `steps` or `notifications/message` payloads.
- Memory contents must be excluded from the structured logging fields used
  for tool calls; only key, scope, and size may appear in logs.
- Sensitive session entries are redacted both from the prompt injection block
  and from model-visible `memory_read` results; caller-facing
  `get_session_memory` may return the value to authorised callers.

## Testing

New test suites:

- `tests/unit/test_memory_store.py` - store invariants: caps, TTL, scope
  isolation, atomicity of partial-write rejection, key validation.
- `tests/unit/test_memory_tools.py` - tool registration, auth gating, error
  contract, event emission, prompt-hardening labelling.
- `tests/integration/test_memory_integration.py` - end-to-end through MCP:
  caller writes a `session` entry, agent reads it on the next `ask`, caller
  clears it, verify isolation across sessions.
- Extend `tests/integration/test_prompt_hardening_adversarial.py` with a
  scenario that injects model-written `<system>` content into a memory value
  and asserts the rendered prompt still treats it as data.

## Resolved design decisions

1. `memory_append` is included in phase one.
2. `reset_session` clears `session`-scope memory for that session.
3. `list_services` does not advertise per-scope quotas; the agent learns
   limits from `quota_exceeded` errors when it hits a cap. No `memory_*`
   capability is added to `list_services` in phase one.
4. No disk persistence in phase one; in-memory only. Revisit when a concrete
   need arises.
5. Memory tools are built-in, not downstream MCP services; they are added by
   `GofrAgent.build()` and do not go through `tool_factory`.
6. Session memory is rendered in the per-run user prompt only, never in
   `build_system_prompt()`.
7. Run-scope memory is owned by `AgentDeps`/`MemoryContext` and discarded
   with the run; session-scope memory lives on `Session` under `session.lock`.
8. Run-scope memory does not require any extra activity beyond `AGENT_ASK`;
   session-scope memory requires `AGENT_MEMORY_READ` / `AGENT_MEMORY_WRITE`.
9. Memory tool calls and results are redacted in reasoning events; values
   never appear in `result.steps` or `notifications/message` payloads.
10. `memory_max_total_bytes` applies to session-scope only; run-scope memory
    has its own per-run entry cap and is not counted against it.

## Out of scope

- Embedding-based semantic memory and retrieval.
- Cross-session or cross-user shared memory.
- Synchronous replication of memory across multiple gofr-agent instances.
- Mutation of structured `provenance` records through memory.

## Approval checklist

- [ ] Scratchpad-first framing and built-in (non-downstream) tool placement
      confirmed.
- [ ] Scope (`run` + `session` only, no cross-session) confirmed.
- [ ] Activity names `GoFRAgentMemoryRead` / `GoFRAgentMemoryWrite` confirmed.
- [ ] Auth split confirmed: run-scope under `AGENT_ASK`; session-scope under
      memory activities.
- [ ] Session memory rendered only in the per-run user prompt, not in
      `build_system_prompt()`.
- [ ] Limits in Configuration table confirmed or adjusted, including the
      run-scope vs session-scope byte budget split.
- [ ] Caller-visible MCP tool surface (`get_session_memory`,
      `set_session_memory`, `clear_session_memory`) confirmed.
- [ ] Sensitive-entry policy confirmed: redacted in prompt and in
      model-visible reads; returned to authorised callers via
      `get_session_memory`.
- [ ] Event redaction policy for memory tool calls/results confirmed.
- [ ] Error contract split confirmed (MCP tools raise `McpError`; agent
      tools return bounded structured payloads).
- [x] Disk persistence: skipped in phase one.
- [x] `memory_append` included in phase one.
- [x] `reset_session` clears `session`-scope memory.
- [x] `list_services` is not modified.
