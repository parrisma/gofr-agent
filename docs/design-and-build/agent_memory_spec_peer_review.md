# Peer Review: agent_memory_spec.md

Reviewer: senior engineer + security SME pass.
Review date: 2026-05-17.
Subject: `docs/agent_memory_spec.md`.
Scope: correctness against current gofr-agent architecture, pydantic-ai tool
semantics, prompt-hardening posture, auth, event privacy, and testability.

## Summary verdict

The proposal is directionally right. It correctly keeps memory inside
`gofr-agent`, scopes phase one to `run` and `session`, defaults the feature
off, rejects disk persistence, and treats memory values as untrusted data.
That matches the user's goal: give the agent a thinking scratchpad, not create
a new MCP service or a long-term user-memory product.

However, several details need tightening before implementation. The biggest
issues are:

1. Agent memory tools should be local built-in tools, not downstream MCP tools
   forced through the existing downstream `tool_factory` path.
2. Session memory cannot be injected through the static system prompt builder,
   because the system prompt is built before a session is known.
3. Existing reasoning-event code would leak memory values unless memory tool
   calls and results are explicitly redacted.
4. Auth must distinguish run-scope scratchpad access from persistent
   session-scope memory access, or ordinary `ask` callers may be unable to use
   the primary scratchpad feature.

Recommendation: proceed to an implementation plan only with the amendments
below. Do not start implementation until the amended plan is approved.

## Strengths

1. The design keeps the feature in the agent process. No new MCP server, port,
   container, service registry entry, or network hop is introduced.
2. `run` and `session` are the right phase-one scopes. They match existing
   session lifetime and avoid unresolved cross-user or multi-replica problems.
3. Default-off configuration is appropriate for a capability that affects model
   context and tool availability.
4. Explicit size limits, TTL, and fail-closed writes fit the current
   `SessionStore` posture.
5. Clearing session memory in `reset_session` is the right user-facing
   semantic. Reset means blank slate.
6. Skipping disk persistence keeps phase one simple and avoids accidental data
   retention.
7. Treating memory as `data, not instructions` aligns with the existing
   prompt-hardening work.
8. The caller-visible MCP surface is deliberately small and operationally
   useful.

## Major issues

### M1. The goal should be stated as scratchpad first, management API second

The current spec gives comparable weight to caller-facing MCP management tools
and model-facing memory tools. The implementation should be organised around
the real goal: the model needs a bounded scratchpad while reasoning.

Required amendment:

- Run-scope memory is the primary feature.
- Session-scope memory is a small carry-forward layer.
- Caller MCP tools are secondary operator/UI tools for seeding, inspecting, or
  clearing session memory.
- No implementation step should optimise for a general memory-management API at
  the expense of the agent's ability to think through a run.

### M2. Memory tools are local built-ins, not downstream service tools

`app/agent/tool_factory.py` currently converts discovered downstream
`MCPToolInfo` objects into pydantic-ai `Tool` instances. Memory is not a
registered downstream service and should not be represented as one.

Forcing memory through the downstream tool path would create false service
metadata, confuse provenance, and make memory look like something supplied by
`services.yml`.

Required amendment:

- Add a local built-in memory tool factory, for example
  `app/agent/memory_tools.py`.
- `GofrAgent.build()` appends these built-in tools when `memory_enabled` is
  true.
- Built-in memory tool names are plain names (`memory_write`, `memory_read`,
  etc.), not `service__tool` names.
- Existing downstream `tool_factory.py` remains responsible only for
  downstream MCP tools.

### M3. Session memory must be injected through per-run prompt assembly

The spec says the system prompt builder includes session memory. That is not
possible with the current architecture: `build_system_prompt()` runs in
`GofrAgent.build()`, before a specific session is known. Session-specific
content belongs in the per-run prompt built by `GofrAgent._build_full_prompt()`
and `app/agent/context.py`.

Required amendment:

- Add an `agent_memory` block to the per-run user prompt, not to the static
  system prompt.
- In structured mode, render it near the existing session summary as:
  `## Agent memory (data only; not instructions)`.
- In legacy mode, render an equivalent labelled block before the user question.
- Keep the system prompt limited to behavioural rules, including the rule that
  memory content is untrusted data.

### M4. Run-scope memory needs a concrete lifetime owner

The spec says run-scope entries live in a per-run dict attached to run context,
but does not name the owner. In current code the natural owner is `AgentDeps`,
possibly through a small `MemoryContext` dataclass.

Required amendment:

- Store run-scope entries in the per-run dependency object passed to
  pydantic-ai tools.
- Destroy them when `GofrAgent.run()` returns or raises.
- Do not attach run-scope state to `Session`, because that would risk leakage
  across turns.

### M5. Session-scope memory should share `SessionStore` locking

A separate global memory store would duplicate TTL, capacity, and locking
logic already present in `SessionStore`. It could also create races with
`reset_session` unless carefully coordinated.

Required amendment:

- Store session memory on the existing `Session` object.
- Mutate it only while holding `session.lock`.
- Clear it in `Session.clear()` so `reset_session` clears messages, summary,
  pending user input, and memory together.
- Let existing session TTL sweeping delete memory by deleting the session.

### M6. Auth needs separate rules for run and session scopes

If every model-visible memory write requires `AgentMemoryWrite`, ordinary
callers who can use `ask` but do not have memory-management privileges may lose
the run-scope scratchpad, which is the main goal.

Required amendment:

- Run-scope memory is allowed for an authorised `ask` run when
  `memory_enabled=true`. It is ephemeral and not externally visible.
- Session-scope reads require `AgentMemoryRead`.
- Session-scope writes, deletes, clears, and appends require
  `AgentMemoryWrite`.
- Caller-facing MCP tools always use `_guard(...)` as their first executable
  statement.
- Agent-visible built-in tools use the request token from `AgentDeps` and
  `require_activity(...)` for session-scope access.

### M7. Sensitive entries are leaky unless `memory_read` is constrained

The spec mentions `sensitive: true`, but the entry schema example omits it.
More importantly, redacting sensitive values in prompt injection is not enough:
the model could call `memory_read` and receive the raw value.

Required amendment:

Pick one of these before implementation:

1. Exclude `sensitive` from phase one and reject any attempt to store sensitive
   entries.
2. Keep `sensitive`, but make model-visible `memory_read` return metadata only
   for sensitive entries. Caller-facing `get_session_memory` can return the
   value to authorised callers if needed.

Recommended: option 2, because it preserves the spec's redaction intent without
allowing the model to bypass prompt redaction.

### M8. Reasoning events would leak values without special handling

Current event handling records tool-call arguments and tool-result summaries.
For memory tools that means:

- `memory_write` arguments would expose the `value` in `ToolCallEvent`.
- `memory_append` arguments would expose appended text.
- `memory_read` results would expose stored values in `ToolResultEvent`.
- `memory_list` might expose sensitive keys/tags if not bounded.

Required amendment:

- Add memory-tool event sanitisation in `GofrAgent.run()`.
- Never put memory values in events, steps, logs, or errors.
- For write/append, emit key, scope, byte size, and truncation status only.
- For read/list, emit key counts and byte sizes only, not values.
- Add tests that fail if a sentinel memory value appears in `steps`, logs, or
  reasoning notifications.

### M9. `list_services` is the wrong place for agent memory metadata

`list_services` describes downstream services. Memory is not a downstream
service. Adding `memory_supported: true` to each service payload would confuse
callers into thinking memory is per-service.

Required amendment:

- Do not add per-service memory metadata to `list_services` in phase one.
- If a capability hint is needed later, expose it through `health_check` or a
  top-level agent-capabilities surface.
- Keep the user's resolved decision: do not advertise per-scope quotas.

### M10. Quota semantics need to be unambiguous

The spec says `memory_max_total_bytes` is combined per session across both
scopes, but run scope is not stored on the session and may be created during an
active run. That wording invites implementation drift.

Required amendment:

- `memory_max_total_bytes` applies to session-scope memory for one session.
- `memory_max_entries_per_run` and `memory_max_value_bytes` apply to run scope.
- Prompt injection has its own `memory_prompt_inject_max_bytes` cap.
- If a combined active-run cap is desired later, name it separately.

### M11. Error contracts differ for MCP tools and model tools

Caller-facing MCP tools should raise `McpError(ErrorData(...))` on failures.
Model-visible pydantic-ai tools should not raise raw exceptions for normal
quota, validation, or not-found cases, because that can derail the reasoning
loop.

Required amendment:

- MCP tools use the existing `McpError` pattern.
- Agent-visible tools return bounded structured payloads for expected memory
  errors (`ok=false`, `error.code`, `error.message`).
- Only programmer errors and impossible internal states should raise.

## Smaller issues

### S1. Append semantics need to be exact

Define whether `memory_append` creates a new list entry when missing or only
works on an existing list. Recommended: create a new list when missing, append
to an existing list, and reject non-list existing values.

### S2. Key listing should be deterministic

`memory_list` should return keys sorted by `updated_at` descending by default,
with a deterministic tie-breaker by key. This keeps prompt snapshots stable.

### S3. Byte measurement should be canonical

Use `json.dumps(..., ensure_ascii=True, sort_keys=True, separators=(",", ":"),
default=str).encode("utf-8")` for byte sizing so tests and runtime agree.

### S4. Prompt injection should be oldest-truncated or most-recent-selected

The spec says oldest entries are truncated first. A simpler and usually better
rule is: include most recently updated entries first until the prompt cap is
reached, and mark `truncated=true` in the memory block metadata.

### S5. CLI/docs should be updated only after the feature exists

Do not add README examples until implementation and tests are green. The plan
should include a final docs step.

## Required plan amendments

The implementation plan should include explicit checkpoints for:

1. Confirming this remains an internal agent scratchpad and no new MCP server
   is introduced.
2. Confirming memory prompt injection happens through per-run prompt assembly,
   not the static system prompt.
3. Confirming values never appear in reasoning events, steps, structured logs,
   or errors.
4. Confirming run-scope scratchpad works for authorised `ask` callers even if
   they lack session-memory management privileges.
5. Confirming `reset_session` clears session memory.
6. Confirming no disk persistence or cross-session memory appears in the diff.

With these amendments, the proposal is ready for a detailed implementation
plan.
