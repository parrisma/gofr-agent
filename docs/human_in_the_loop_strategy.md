# Human-in-the-loop Strategy

Status date: 2026-05-17 (revision 3, Phase 1A implemented).

## Summary

gofr-agent can show live reasoning while an `ask` call is running and Phase 1A
now supports deterministic pause/resume for pre-LLM missing-field prompts. The
older `clarification_request` field remains the non-interactive fallback: it is
a successful final response, not a pause/resume mechanism.

The full recommended design remains a first-class pause/resume protocol over
MCP: when the agent needs the user, `ask` returns `status: "waiting_for_user"`
with a bounded prompt object; the client calls a response tool with the user's
answer; the server resumes work without holding the original MCP request open.
Phase 1A implements this for deterministic missing-field prompts before the LLM
run starts. Phase 1B will extend the same envelope to LLM-initiated prompts
using pydantic-ai native deferred-tool support.

This revision incorporates findings from
`docs/human_in_the_loop_strategy_peer_review.md`.

## Constraints and deployment assumptions

1. Single-replica only for v1. Pending-run state is process-local (same
   constraint as `SessionStore`). If gofr-agent is ever deployed behind a
   load balancer, sticky routing by `session_id` is mandatory. Clustered
   durability is out of scope for v1 (see Phase 4).
2. Subject-bound authorization is required (see Security). If `AuthService`
   does not yet expose a stable subject claim, the feature ships only
   behind a `--allow-unauthenticated-resume` developer flag and is
   disabled in production builds.
3. ASCII-only payloads in events and stored state, per repo rule R6.
4. No bearer tokens are ever stored on the server; resume must present a
   fresh token (see Security).

## Alternatives considered

### A. MCP elicitation (`ctx.elicit()`)

`mcp>=1.26.0` and FastMCP both ship a first-class human-input primitive:
`Context.elicit(message, response_type, ...)` from the server side, backed by
an `elicitation/create` JSON-RPC request to the client and capability
advertisement via `ElicitationCapability` (`FormElicitationCapability`,
`UrlElicitationCapability`). See
`mcp/server/session.py` (`elicit_form`, `elicit_url`,
`send_elicit_complete`) and `fastmcp/server/context.py`
(`Context.elicit`).

Rejected for v1 as the primary mechanism because:

1. `ctx.elicit()` keeps the originating `ask` tool-call request open for the
   entire human think time. That violates the Goal of not blocking on human
   latency and does not survive client reconnects.
2. mcpo and many MCP-over-HTTP proxies do not reliably round-trip
   server-initiated requests, which would break the OpenAI-compatible
   surface on port 8091.
3. Auth, audit, and activity-based authorisation want the resume to be a
   normal authenticated client-to-server tool call, not an inverted
   server-to-client RPC.

A future short-prompt mode may opt into `ctx.elicit()` for sub-second
prompts handled inside one HTTP cycle. Out of scope for v1.

### B. SSE side channel / WebSocket sidecar

Rejected. Would add a second transport, duplicate auth, and complicate the
React integration. The existing MCP Streamable HTTP transport plus
notifications is sufficient.

### C. HTTP `/agent/ask/respond` route

Sketched in `docs/react_integration_guide.md` section 5b. Rejected in favor
of an MCP tool so the resume reuses the same transport, auth middleware,
activity checks, and reasoning notification stream as `ask`.

### D. Deterministic clarification only (current behaviour)

Kept as the Phase 0 fallback and as the non-interactive default. Not
sufficient on its own because clarifications discovered mid-run by the LLM
cannot be surfaced without restarting the turn.

## Current review

| Area | Current state | Human-input implication |
|------|---------------|-------------------------|
| MCP server | `app/mcp_server/mcp_server.py` exposes `ask`, `respond_to_user_input`, `get_pending_user_input`, and `cancel_user_input`. | Phase 1A can persist and resume deterministic pending prompts. Phase 1B still needs native pydantic-ai deferred run storage. |
| Agent runner | `app/agent/agent.py` builds a pydantic-ai `Agent` with `output_type=str` and streams `ModelRequestNode` / `CallToolsNode` events until `End`. | Native deferred tools are not enabled yet; LLM-initiated prompts remain Phase 1B. |
| Events | `app/agent/events.py` supports live reasoning notifications, user-input events, run IDs, and final `steps`. | Phase 1A events are available for prompt, pause, receive, resume, and cancel flows. |
| Clarification | `app/agent/contracts.py` and `app/agent/verification.py` define `ClarificationRequest` and `HumanInputRequest`. `GofrAgent.run` can pause before the LLM when interactive mode and verification-gap responses are enabled. | Non-interactive callers still receive the existing final clarification response. |
| Sessions | `app/sessions/backend.py` stores `messages`, `summary`, timestamps, a lock, and one pending user-input record. | Pending state is process-local, TTL-bound, and contains no bearer token. |
| CLI | `app/cli/ask.py` renders reasoning notifications and final payloads. | `--interactive` sends interactive asks; JSON mode exposes waiting payloads, and TTY text mode can answer prompts. |
| React docs | `docs/react_integration_guide.md` documents the Phase 1A MCP pause/resume protocol. | React clients should check `status`, render `user_input_request`, and call the resume/cancel/lookup tools directly. |

The installed pydantic-ai package already includes the primitive we need:
`DeferredToolRequests`, `DeferredToolResults`, `CallDeferred`, `ApprovalRequired`,
`ToolApproved`, `ToolDenied`, and `Agent.iter(..., deferred_tool_results=...)`.
That means gofr-agent should lean on the framework rather than inventing a
parallel control loop.

## Goals

1. Let the agent ask for missing user-owned information while preserving prior
   reasoning, tool calls, and model context.
2. Keep MCP Streamable HTTP as the only transport surface.
3. Preserve current behavior unless the caller opts into interactive runs or a
   server-side flag enables them.
4. Avoid waiting on an open request for human response time.
5. Reauthorize resume requests and never store bearer tokens in session state.
6. Treat user responses as caller content, not as higher-priority system or
   developer instructions.

## Non-goals for the first version

1. Multi-process durability. Sessions are already process-local; pending prompts
   can follow that constraint initially.
2. Browser push outside MCP notifications. Existing MCP logging notifications
   are enough for prompt events.
3. General risky-action approval for every downstream tool. That should be a
   follow-up built on pydantic-ai `requires_approval`.

## Recommended protocol

Add an opt-in interactive mode to `ask`:

```json
{
  "question": "Calculate the return, but ask me if anything is missing",
  "session_id": "ui-session-1",
  "interactive": true,
  "max_steps": 25
}
```

Extend the `ask` response with a `status` field and a stable `run_id` that
spans pause and resume. Existing fields are preserved; `answer` is left empty
when `status == "waiting_for_user"` so legacy clients that ignore `status`
do not display the prompt as if it were a final answer.

```json
{
  "status": "waiting_for_user",
  "is_complete": false,
  "session_id": "ui-session-1",
  "request_id": "req-123",
  "run_id": "run-7c1",
  "answer": "",
  "user_input_request": {
    "prompt_id": "hVj8...opaque-128-bit...",
    "run_id": "run-7c1",
    "session_id": "ui-session-1",
    "prompt": "Please provide the ticker and date range.",
    "input_schema": {
      "type": "object",
      "properties": {
        "ticker": {"type": "string"},
        "date_range": {"type": "string"}
      },
      "required": ["ticker", "date_range"]
    },
    "choices": null,
    "created_at": "2026-05-17T00:00:00Z",
    "expires_at": "2026-05-17T00:10:00Z"
  },
  "steps": [],
  "model": "deepseek/deepseek-v4-pro",
  "tokens_used": 0,
  "verification_gap": null,
  "clarification_request": null,
  "provenance": []
}
```

Notes on the envelope:

- `run_id` is the stable identifier of the logical pause/resume cycle.
  `request_id` continues to identify a single HTTP/MCP call. The resume
  response carries the same `run_id` so clients can stitch events.
- `prompt_id` is opaque, at least 128 bits of CSPRNG entropy
  (`secrets.token_urlsafe(24)`), and never logged in full.
- `is_complete` is a back-compat hint for clients that do not consume
  `status`.

When the user answers, the client calls a new MCP tool:

```json
{
  "tool": "respond_to_user_input",
  "arguments": {
    "session_id": "ui-session-1",
    "prompt_id": "prompt-abc",
    "value": {"ticker": "AAPL", "date_range": "2026-01-01 to 2026-05-17"}
  }
}
```

`respond_to_user_input` returns the same response envelope as `ask`. In Phase
1A it resumes with `interactive=false`, so the normal outcome is
`status: "completed"` or a non-interactive clarification response. Returning a
second `status: "waiting_for_user"` is reserved for Phase 1B.

Add two small operational tools:

| Tool | Purpose |
|------|---------|
| `get_pending_user_input(session_id, prompt_id=None)` | Allows a reconnecting UI to recover pending prompt state. |
| `cancel_user_input(session_id, prompt_id, reason=None)` | Lets the user cancel a paused run and clears pending state. |

All three tools are protected by dedicated activities. FastMCP/mcpo may still
list them to an outer model in Phase 1A; do not rely on tool hiding as a
security boundary. The React UI and CLI invoke them directly over MCP, and
server-side authorization remains mandatory.

Add activity constants alongside the existing ones:

| Activity | Tool |
|----------|------|
| `GoFRAgentRespondToUserInput` | `respond_to_user_input` |
| `GoFRAgentGetPendingUserInput` | `get_pending_user_input` |
| `GoFRAgentCancelUserInput` | `cancel_user_input` |

## Event contract additions

The existing reasoning stream should emit these additional event kinds:

| `kind` | Meaning |
|--------|---------|
| `user_input_requested` | A prompt is ready for the client to show. |
| `run_paused` | The logical run is paused until the prompt is answered or cancelled. |
| `user_input_received` | A resume request supplied an answer. Do not include sensitive raw values unless bounded and explicitly safe. |
| `run_resumed` | The agent has resumed from a pending prompt. |
| `user_input_cancelled` | The pending prompt was cancelled or expired. |

Every event should keep the existing shared fields: `request_id`, `session_id`,
`event_id`, `sequence`, `kind`, and `timestamp`. Prompt events should also carry
`prompt_id`.

## Agent implementation shape

### 1. Add a model-visible user-input tool

Add an internal tool such as `ask_user` to the pydantic-ai tool list. It should
be exposed only when the run is interactive, using a `prepare` hook keyed off
`AgentDeps`.

The tool should accept bounded, structured prompt arguments:

```python
async def ask_user(
    ctx: RunContext[AgentDeps],
    prompt: str,
    input_schema: dict | None = None,
    choices: list[str] | None = None,
) -> str:
    raise CallDeferred(metadata={"kind": "gofr.user_input"})
```

This is an external deferred call, not a tool-approval call. pydantic-ai will
return a `DeferredToolRequests` object with the model's tool-call arguments and
tool-call ID. The server stores that object and returns `waiting_for_user`.

Server-side validation applied before the prompt is surfaced or stored:

- `prompt`: max 2048 characters; strip control characters except `\n`.
- `choices`: optional list, max 20 entries, each max 256 characters.
- `input_schema`: optional JSON schema; max serialized size 4 KiB; allowed
  keywords restricted to a safe subset (`type`, `properties`, `required`,
  `items`, `enum`, `description`, `minLength`, `maxLength`, `minimum`,
  `maximum`, `pattern`); reject `$ref`, `allOf`, and unbounded recursion.
- Per-run prompt budget: maximum 5 `ask_user` invocations across a single
  logical run. The sixth attempt returns a hard error to the model (via
  the deferred-tool denial path) so the loop terminates.

### 1a. Multi-call pauses

`DeferredToolRequests.calls` is a list; the model may emit multiple
`ask_user` calls in one step. For v1 the rule is **one pending prompt per
pause**. If the engine receives a `DeferredToolRequests` with
`len(calls) > 1`, it accepts `calls[0]` as the pending prompt, synthesises
denial `DeferredToolResults` for the remaining calls in the same step, and
records a `user_input_extras_denied` event. The denial message instructs
the model to ask one question at a time.

### 2. Enable deferred output only for interactive runs

Current code uses:

```python
Agent(..., output_type=str, ...)
```

For an interactive run, call `self._agent.iter` with:

```python
output_type=[str, DeferredToolRequests]
```

For non-interactive runs, keep the current output type and omit `ask_user` from
the model-facing tool list. This keeps old clients stable.

### 3. Store a pending run, not just a prompt

When `agent_run.result.output` is `DeferredToolRequests`, store a pending object
on the session. The full pydantic-ai message state at the pause point is
captured verbatim via `all_messages()` so the resume does not have to
reconstruct anything:

```python
PendingUserInput(
    prompt_id=secrets.token_urlsafe(24),  # >=128 bits CSPRNG
    run_id=run_id,                         # spans pause/resume
    request_id=request_id,                 # original ask request
    tool_call_id=deferred_requests.calls[0].tool_call_id,
    deferred_requests=deferred_requests,
    full_history=agent_run.all_messages(), # NOT new_messages()
    original_question=question,
    run_options={
        "max_steps": max_steps,
        "model_override": model_override,
        "tool_calls_used": agent_run.usage().total_tool_calls,
    },
    event_steps=event_sink.build_steps(),
    prompt_count=event_sink.prompt_count + 1,
    subject=auth_context.subject,          # bound at pause time; see Security
    created_at=now,
    expires_at=now + ttl,
)
```

Do not store the bearer token. Resume with the token from the new
`respond_to_user_input` request, and re-authorise against the stored
`subject`.

Concurrency rules while a session holds a pending prompt:

1. New `ask` calls on the same `session_id` are rejected with a typed
   error pointing at the pending `prompt_id`.
2. `respond_to_user_input` is guarded by a compare-and-swap on
   `prompt_id`: the pending object is atomically cleared as the first
   step of resume. A second concurrent resume call with the same
   `prompt_id` finds nothing and returns an idempotent "already
   resolved" response.
3. `cancel_user_input` uses the same compare-and-swap.
4. The existing per-session lock continues to serialise mutations to
   `session.messages`.

### 3a. Sanitisation on cancel, expiry, and abandonment

The stored `full_history` contains an unresolved tool-call part. If left
in place and merged back into the session, future `ask` calls will
corrupt or error inside pydantic-ai. On cancel, TTL expiry, or process
restart recovery, the engine must sanitise the history before any
further turn. Mirror the approach in
`pydantic_ai/ui/_adapter.py:sanitize_messages`: synthesise a
`ToolReturnPart` for the dangling `tool_call_id` carrying a bounded
cancellation marker (`{"cancelled": true, "reason": "<reason>"}`), then
append the sanitised slice to `session.messages`. This preserves
context while keeping the message graph well-formed.

Process restart: pending state is in-memory and is lost. Clients
holding a `prompt_id` will receive `prompt_not_found` from
`respond_to_user_input` and `get_pending_user_input`. This is
acceptable for v1 given the single-replica constraint.

### 4. Resume with `DeferredToolResults`

`respond_to_user_input` loads the pending object via compare-and-swap on
`prompt_id`, validates TTL, re-authorises the caller against the stored
`subject`, validates the response value against `input_schema`, and then
resumes the agent.

Key contract details verified against
`pydantic_ai/_agent_graph.py:_handle_deferred_tool_results` and
`pydantic_ai/ui/_adapter.py`:

- Pass the full pause-time history via `message_history`. Do **not**
  concatenate `base + new_messages()`; that risks dropping or duplicating
  system parts.
- Do **not** pass a `user_prompt`. With `deferred_tool_results` set,
  pydantic-ai injects the tool-return parts directly; a fresh user prompt
  would introduce a spurious `UserPromptPart` and confuse the model.
- `UsageLimits.tool_calls_limit` is per `Agent.iter` invocation. Compute
  the remaining budget yourself from `pending.run_options["tool_calls_used"]`
  and the original `max_steps`.

```python
deferred_results = DeferredToolResults(
    calls={pending.tool_call_id: validated_value},
)

remaining = max(
    0,
    pending.run_options["max_steps"] - pending.run_options["tool_calls_used"],
)

async with self._agent.iter(
    user_prompt=None,
    message_history=pending.full_history,
    deferred_tool_results=deferred_results,
    output_type=[str, DeferredToolRequests],
    deps=AgentDeps(
        token=resume_token,
        request_id=resume_request_id,
        run_id=pending.run_id,
        ...,
    ),
    usage_limits=UsageLimits(tool_calls_limit=remaining),
) as agent_run:
    ...
```

After the resumed run completes, append the final `all_messages()` slice
starting from the original session tail to `session.messages` exactly
once, clear pending state, run summary compaction, and return the normal
final payload. If the resumed run produces another `DeferredToolRequests`,
repeat the pause cycle with a new `prompt_id` (same `run_id`).

### 5. Preserve deterministic clarification behavior

The existing missing-field detection should stay useful:

- If `interactive` is false, keep returning `clarification_request` as a final
  successful response.
- If `interactive` is true, convert the deterministic clarification into a
  `waiting_for_user` prompt without calling the LLM.

That gives UIs immediate ask-back for obvious missing inputs and gives the LLM
the `ask_user` tool for missing information discovered mid-run.

## Client behavior

### React UI

1. Continue subscribing to `notifications/message` for reasoning events.
2. When `user_input_requested` arrives, show a modal or inline prompt attached
   to the active turn.
3. Disable the normal send button for that session while `status` is
   `waiting_for_user`, or route the next user message to `respond_to_user_input`.
4. Call `get_pending_user_input` after reconnect or page refresh.
5. Render the final response returned by `respond_to_user_input` as the same
   agent turn, not as a separate unrelated turn.

### CLI

In text mode, the CLI can loop automatically:

1. Call `ask` with `interactive=True`.
2. If the response is `waiting_for_user`, prompt on stdin when attached to a
   TTY.
3. Call `respond_to_user_input` and repeat until `completed` or cancelled.

In JSON mode, the CLI should not prompt interactively. It should print the
`waiting_for_user` payload so scripts can decide how to respond.

## Security and correctness notes

1. **Prompt text is model-generated.** Bound length (2048 chars), strip
   control characters, and treat as UI text only. Never interpolate prompt
   text into server logs or other model contexts.
2. **User response values are caller content.** They must not override
   system prompt, developer policy, service descriptions, or authenticated
   requester instructions. Inject only as the deferred tool's return value.
3. **Prompt IDs are bearer-grade secrets.** Generate with
   `secrets.token_urlsafe(24)` (>=128 bits). Compare with `hmac.compare_digest`.
   Never log full prompt IDs; log a short prefix only.
4. **Subject binding is required.** At pause time, capture the caller's
   stable subject (from `AuthService`). Resume must present a token whose
   subject matches exactly. If `AuthService` cannot yet expose a subject
   claim, the feature ships only behind
   `--allow-unauthenticated-resume` (dev-only flag, not allowed in
   production builds). `session_id` is a routing key only and is **not**
   used for authorisation.
5. **Token-scope downgrade policy.** The resume token's permitted
   activities must be a superset of the activities permitted at pause
   time. Any narrower scope causes resume to fail closed with
   `auth_scope_narrowed`. This prevents an operator with reduced
   privileges silently continuing a privileged run.
6. **No bearer tokens stored.** Resume uses the resume request's token.
7. **Pending prompts need TTL cleanup** through the existing session
   sweep path. Sweep must run sanitisation (Section 3a) before discarding.
8. **Per-run prompt budget** (default 5) prevents the model trapping the
   user in a loop.
9. **`max_steps` arithmetic across resume**: store `tool_calls_used` at
   pause, pass `tool_calls_limit = max_steps - tool_calls_used` on resume.
10. **No secrets in events**, no unbounded prompt or response payloads,
    no raw `input_schema` echoed into logs.

## Implementation phases

### Phase 0: UI fallback available now

Clients can already handle `clarification_request` by asking the user a follow-up
question and sending another `ask` call with the same `session_id`. This is not
true pause/resume, but it is usable before server changes.

### Phase 1A: Deterministic clarification rendered as `waiting_for_user`

Lowest-risk slice. No pydantic-ai deferred tools involved.

1. Add `HumanInputRequest`, `HumanInputResponse`, `AgentResult.status`,
   `AgentResult.is_complete`, and `AgentResult.run_id` models.
2. Extend session state with one pending prompt per session, including the
   subject binding fields (see Security).
3. Add MCP tools `respond_to_user_input`, `get_pending_user_input`,
   `cancel_user_input` (model-hidden) and matching activity constants.
4. Add event models and renderer support for the new event kinds.
5. When `interactive=True` and the deterministic verification gap fires,
   convert the existing `ClarificationRequest` into `waiting_for_user`.
   The resume path for this case does **not** use pydantic-ai deferred
   tools: it composes a synthetic follow-up question from the user's
   response and invokes the agent as a fresh turn. This proves the
   protocol end to end without the resume engine.

### Phase 1B: Native pydantic-ai deferred `ask_user`

1. Add `interactive` and prompt-budget fields to `AgentDeps`.
2. Register `ask_user` with a prepare hook so it is visible only for
   interactive runs.

### Phase 2: Native pydantic-ai deferred `ask_user`

1. Add `interactive` and prompt-budget fields to `AgentDeps`.
2. Register `ask_user` with a prepare hook so it is visible only for interactive
   runs.
3. Run interactive turns with `output_type=[str, DeferredToolRequests]`.
4. Store `DeferredToolRequests` plus `all_messages()` when the model calls
   `ask_user`.
5. Resume with `DeferredToolResults` from `respond_to_user_input`, using
   the contract details in Section 4.
6. Implement multi-call denial (Section 1a) and sanitisation on cancel /
   expiry (Section 3a).
7. Add focused unit and MCP integration tests (see Test plan).

### Phase 3: Human approval for risky tools

Use pydantic-ai `requires_approval` or `ApprovalRequired` for downstream tools
that should be explicitly approved before execution. This should be separate
from `ask_user`: approvals answer "may I do this?" while user input answers
"what value should I use?".

### Phase 4: Durability and multi-replica support

Move session and pending-run state to a shared backend if gofr-agent needs more
than one replica. Until then, deployment should use sticky routing for sessions.

## Test plan

Core unit and contract tests:

1. Contract model serialization, including `status`, `is_complete`, and
   `run_id`.
2. Event model serialization for the new `kind` values.
3. `secrets.token_urlsafe` length and `hmac.compare_digest` usage are
   exercised by tests that pass near-miss prompt IDs.

Session and storage tests:

4. Pending prompt create, get, cancel, TTL expiry, and sweep.
5. Sanitisation on cancel and expiry produces a well-formed
   `ToolReturnPart` for the dangling `tool_call_id` (Section 3a).
6. Compare-and-swap on `prompt_id`: concurrent `respond_to_user_input`
   races produce exactly one resume and one idempotent "already
   resolved" response.
7. New `ask` on a session with pending input is rejected with a typed
   error pointing at the pending `prompt_id`.

Agent engine tests:

8. Fake pydantic-ai run returning `DeferredToolRequests` with one call
   resumes correctly.
9. Fake run returning `DeferredToolRequests` with multiple calls
   surfaces `calls[0]` and denies the rest (Section 1a).
10. Resume passes `message_history=full_history`, no `user_prompt`,
    and correct `tool_calls_limit` arithmetic.
11. Resume that itself returns another `DeferredToolRequests` produces a
    new `prompt_id` under the same `run_id`.
12. `interactive=False` keeps the existing clarification-as-final-response
    path byte-for-byte unchanged (regression).

Auth and security tests:

13. Resume by a different subject is rejected (`subject_mismatch`).
14. Resume with a narrower token scope is rejected (`auth_scope_narrowed`).
15. `respond_to_user_input` with `input_schema` validation failure is
    rejected and the pending prompt is preserved.
16. Per-run prompt budget hard-caps at the configured maximum.
17. mcpo surface check: model-hidden tools are not exposed to an outer
    LLM.

MCP server and CLI tests:

18. MCP server tests for unknown / expired / mismatched prompt IDs and
    response envelope shape under each `status` value.
19. CLI text-mode auto-loop enforces prompt budget and a wall-clock cap.
20. CLI JSON-mode prints the `waiting_for_user` payload without
    prompting.

Integration tests over Streamable HTTP:

21. End-to-end pause/resume run emits notifications in order:
    `run_started`, ..., `user_input_requested`, `run_paused`,
    `user_input_received`, `run_resumed`, ..., `run_completed`. All
    notifications carry the same `run_id`.
22. `get_pending_user_input` after simulated client reconnect returns
    the same prompt object.
23. Server restart between pause and resume: client receives
    `prompt_not_found` and the session can start a fresh `ask` without
    error (proves sanitisation on recovery).

Run tests with `./scripts/run_tests.sh`, using targeted `-k` slices first
and a full suite before merging.

## Resolved questions

1. **Interactive mode surface.** `ask` parameter plus default-off config
   (`GOFR_AGENT_INTERACTIVE_DEFAULT=false`). Resolved.
2. **Pending prompts per session.** One. Multi-call pauses are handled by
   the denial rule in Section 1a. Resolved.
3. **Prompt ownership / identity.** Stable subject from `AuthService` is
   required. Without it the feature is dev-only behind
   `--allow-unauthenticated-resume`. `session_id` is never used for
   authorisation. Resolved.
4. **File/blob references in responses.** Out of scope for v1. Only
   bounded JSON and text values. Resolved.
5. **Cancelled prompts in session history.** Record a bounded
   cancellation event and synthesise a `ToolReturnPart` with the
   cancellation marker so the message graph is well-formed (Section 3a).
   Do not preserve the model's unresolved tool call verbatim. Resolved.
6. **Prompt TTL default.** 10 minutes. Configurable via
   `GOFR_AGENT_PENDING_PROMPT_TTL_SECONDS`. Resolved.
7. **Notifications during the pause window.** None emitted. Clients use
   `get_pending_user_input` for recovery. Resolved.
8. **Composition with `requires_approval`.** Out of scope for v1; Phase 3
   follow-up. Resolved.

## Outstanding items to verify before implementation

1. Empirically confirm that `Agent.iter(message_history=all_messages(),
   deferred_tool_results=...)` with no `user_prompt` is the correct
   resume contract in the currently pinned pydantic-ai version. Lock the
   version once verified.
2. Confirm that FastMCP's tool-hidden convention used by the existing hub
   tools is honoured by mcpo. If not, add an mcpo-side allowlist.
3. Confirm that `AuthService` exposes a stable subject claim; if not,
   land that work first or accept the dev-only constraint above.