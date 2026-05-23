# Peer review: human_in_the_loop_strategy.md

Reviewer: senior engineer + security SME pass.
Review date: 2026-05-17.
Subject: `docs/human_in_the_loop_strategy.md` (first draft, untracked).
Scope: correctness against pydantic-ai and MCP semantics, security,
concurrency, completeness, alternatives, test plan, risks.

## Summary verdict

The proposal is structurally sound and correctly identifies the pydantic-ai
deferred-tool primitive as the right reasoning-loop mechanism. However, it has
one large miss (MCP elicitation), several correctness gaps in the resume
machinery, and material security and concurrency holes. It is not ready to be
promoted to an implementation plan. With the fixes below it should be.

Recommendation: revise the strategy doc to address Major issues 1-8, then
write a separate `docs/<feature>_implementation_plan.md` per repo rule A2.

## Strengths

1. Correctly diagnoses that `clarification_request` is a final response, not
   pause/resume.
2. Picks the right pydantic-ai primitive (`DeferredToolRequests` /
   `DeferredToolResults`) instead of building a parallel control loop.
3. Opt-in via `interactive=true` preserves the existing `ask` contract.
4. Does not hold an HTTP/MCP request open during human think time.
5. Explicitly refuses to store bearer tokens in pending state.
6. Treats user response as caller content, not as elevated instructions.
7. Phased delivery with a phase 0 that requires no server change.

## Major issues

### M1. MCP elicitation is not considered

`mcp>=1.26.0` and FastMCP both ship a first-class human-input protocol:
`ctx.elicit(message, response_type, ...)` from the server side, returning
`AcceptedElicitation | DeclinedElicitation | CancelledElicitation`, with
client capability advertisement (`ElicitationCapability`,
`FormElicitationCapability`, `UrlElicitationCapability`) and a transport-level
`elicitation/create` request. See
`.venv/lib64/python3.11/site-packages/mcp/server/session.py` (`elicit_form`,
`elicit_url`, `send_elicit_complete`) and
`.venv/lib64/python3.11/site-packages/fastmcp/server/context.py`
(`Context.elicit`).

The proposal invents `respond_to_user_input`, `get_pending_user_input`, and
`cancel_user_input` MCP tools that duplicate this standard surface. The
strategy doc must at minimum:

1. Acknowledge MCP elicitation exists.
2. Document why custom tools are still preferred. The honest reasons are:
   - `ctx.elicit()` keeps the originating `ask` tool-call request open for
     the entire human think time, which violates the proposal's Goal #4 and
     does not scale across reconnects or long pauses.
   - Streamable HTTP plus React UI cannot easily round-trip an
     `elicitation/create` JSON-RPC request because mcpo and many proxies do
     not support server-initiated requests reliably.
   - Auth, audit, and activity-based authorization want the resume to be a
     normal authenticated tool call, not an inverted server-to-client RPC.
3. Optionally support `ctx.elicit()` as a short-prompt mode (sub-second
   prompts inside one HTTP cycle) and document the cut-over.

Without this section the design will be rejected on first review by anyone
familiar with MCP.

### M2. Resume message-history construction is probably wrong

The doc proposes:

```
message_history = pending.base_history + pending.paused_new_messages
```

with `paused_new_messages = agent_run.new_messages()`.

Verify against `pydantic_ai/_agent_graph.py:_handle_deferred_tool_results`
before committing. The safer pattern is:

```
message_history = agent_run.all_messages()
```

captured at the moment `DeferredToolRequests` is returned, stored verbatim,
then passed back to a fresh `Agent.iter(...)` with `deferred_tool_results=...`
and `user_prompt=None`. Concatenating `base_history + new_messages()` risks:

- Dropping system/instructions parts that pydantic-ai materialises into the
  request node.
- Duplicating model parts if `base_history` already overlaps with what
  `new_messages()` reports.
- Diverging from how pydantic-ai's own `ui` adapter resumes paused runs (see
  `pydantic_ai/ui/_adapter.py`).

Also: passing `"Continue with the user's response."` as the user prompt on
resume is wrong. With `deferred_tool_results` set, pydantic-ai expects no new
user prompt; supplying one will inject a spurious `UserPromptPart` that
confuses the model.

Action: replace the snippet with a verified resume pattern, anchored by a
reference to the exact pydantic-ai code path that consumes it.

### M3. The proposal assumes one `ask_user` per pause, but `DeferredToolRequests` is a list

`DeferredToolRequests.calls` is a list. The model can emit multiple `ask_user`
calls in the same step. The proposal collapses this to a single
`tool_call_id` and a single `prompt_id`, which means:

- The server must either reject multi-call pauses (constrain via tool
  description and validate post-hoc), or
- Support N pending prompts per pause and require the client to answer all
  before resuming.

Pick one and write it down. If single-prompt is the rule, describe the
enforcement: on receiving a `DeferredToolRequests` with `len(calls) > 1`,
synthesise denial results for the extras and only surface call[0]. That has
to be explicit, not implicit.

### M4. Pending-state corruption on expiry, cancel, and server restart

The sessions store is in-memory (`SessionStore`, process-local, TTL-swept).
On any of the following events the conversation history will contain an
unresolved tool-call part:

- TTL expiry of the pending prompt.
- Explicit `cancel_user_input`.
- Process restart (sessions vanish, but a client may already hold a
  `prompt_id` and try to resume).

If the user then issues a new `ask` against the same `session_id`, the
message history will either error inside pydantic-ai or confuse the model.
The proposal must specify history sanitisation on cancel/expiry: either
(a) synthesise a `ToolReturnPart` carrying a cancellation marker for the
deferred tool call before storing the messages back into the session, or
(b) discard the entire paused turn from the session. Option (a) preserves
context; (b) is simpler.

This is the same problem `pydantic_ai/ui/_adapter.py:sanitize_messages`
solves. Cite it.

### M5. Authorization model is under-specified and exploitable as written

The proposal currently relies on three things to authorise a resume:
the `GoFRAgentRespondToUserInput` activity, the `session_id`, and the
`prompt_id`. With current behaviour:

- `session_id` is caller-chosen and may be predictable (the README and
  React guide use trivial strings like `"test-s"`).
- `prompt_id` is server-generated, but the doc does not require it to be
  cryptographically random or compared in constant time.
- There is no binding between the original `ask` caller's identity and the
  resume caller's identity.

Net effect: anyone who holds the response activity and can guess or observe
a session/prompt pair can hijack a paused run, inject answers, and read the
subsequent reasoning notifications.

Required fixes before any code:

1. `prompt_id` must be at least 128 bits of CSPRNG entropy (e.g.
   `secrets.token_urlsafe(24)`), opaque, never logged in full.
2. All lookups must be constant-time on `prompt_id`.
3. The pending object must record a stable caller identity captured at
   pause time, and the resume must require an equal identity. If
   `AuthService` cannot yet expose a subject claim, scope this feature to
   single-tenant deployments and document the constraint up front.
4. Treat `session_id` as untrusted for authorization; it is a routing key
   only.

### M6. Token-scope downgrade across resume is not addressed

The original `ask` runs under token A. The resume runs under token B. If
token B has fewer permitted activities (e.g. an admin started the run, an
operator resumed it), what wins for the rest of the run?

The doc says only "Reauthorize resume requests". That is necessary but not
sufficient. Add an explicit rule, e.g.:

- The intersection of activities permitted at pause and at resume governs
  any downstream tool call made after resume, OR
- Freeze the authorisation context at the original `ask` and reject resume
  if the resumer cannot present a token whose activities are a superset
  (this rejects downgrade entirely).

Either is defensible; silence is not.

### M7. Single-replica assumption is hidden

Pending state is in-memory. If gofr-agent is ever deployed behind a load
balancer without sticky session routing, `respond_to_user_input` will land
on a replica with no pending object and silently 404. The proposal's
non-goal #1 mentions "Sessions are already process-local" but the
implication for routing is never stated.

Add a top-line constraint: "This feature requires single-replica or
session-id-sticky routing; clustered durability is out of scope for v1."

### M8. Reasoning notifications across the pause boundary

The current notification stream is anchored to the MCP request that called
`ask`. After pause, the next reasoning events come from a different MCP
request (`respond_to_user_input`). The React subscriber listens at the
session level for `notifications/message` so events are still received, but
the doc must make two things explicit:

1. `request_id` should be reused across the same logical run so the client
   can correlate the two batches. A separate `run_id` or `turn_id` field is
   cleaner; introduce one rather than overloading `request_id`.
2. No notifications are emitted during the pause window itself. Clients
   needing UI heartbeat must rely on `get_pending_user_input` or render the
   `run_paused` event as the steady state.

## Smaller issues

### S1. The response envelope conflates "answer" with "prompt"

The example payload puts the model's prompt text into the `answer` field:

```
"answer": "Please provide the ticker and date range."
```

Old clients that ignore `status` will display this prompt as if the
question had been answered. Either set `answer` to empty when
`status == "waiting_for_user"`, or add an `is_complete: false` flag for
back-compat.

### S2. Validation of model-supplied `input_schema`

`ask_user(prompt, input_schema=None, choices=None)` lets the model send an
arbitrary JSON schema through to the UI and back. Two requirements not in
the doc:

1. Server must bound and validate `input_schema` (size, depth, allowed
   keywords) before relaying.
2. Server must validate the user's response against the schema on
   `respond_to_user_input` before injecting it as a tool result, otherwise
   the model may receive structurally invalid data.

### S3. Prompt-text safety

The proposal correctly says "strip control characters". Add:

- A maximum length (suggest 2048 chars).
- A maximum number of `choices` (suggest 20).
- A maximum total prompts per run (suggest 5, hard cap, surfaced as an
  error to the model so it stops asking).

### S4. `max_steps` arithmetic across resume

The doc proposes `UsageLimits(tool_calls_limit=remaining_steps)`. Verify
empirically: pydantic-ai's `UsageLimits` are per `Agent.iter` invocation
and may not see tool calls from the prior run. If that is true, you must
track a running count in the pending object and reduce the limit yourself
(which the doc says, but the example code does not show clearly).

### S5. Phase 1 ships a half feature

Phase 1 promises a `waiting_for_user` flow for the deterministic
clarification path only, but also lists "Add MCP tools for respond, get
pending, and cancel". Without phase 2's deferred-tool engine, those tools
work only for the deterministic case. Split:

- Phase 1A: deterministic clarification rendered as `waiting_for_user`,
  resume implemented by synthesising a fresh `ask` internally (no
  pydantic-ai deferred tools). Low risk, useful.
- Phase 1B: full deferred-tool `ask_user`, with all the resume mechanics.

### S6. Tool visibility to the LLM

`respond_to_user_input` is a normal MCP tool, so when gofr-agent is fronted
by mcpo and exposed to an outer LLM, that LLM will see it as a callable.
Mark these tools as model-hidden using the same convention as existing hub
tools, and verify mcpo respects the hint.

### S7. Test-plan gaps

The current draft does not enumerate tests. At minimum cover:

- Multi-`ask_user` per step (M3 enforcement).
- Cancel during resume execution (race).
- Double `respond_to_user_input` with the same `prompt_id` (idempotent).
- `respond_to_user_input` with a value failing input_schema validation.
- Expiry sweep removes pending state and sanitises messages (M4).
- Token-downgrade between pause and resume (M6).
- Reconnect path: `get_pending_user_input` returns the same prompt object.
- `interactive=False` keeps the existing clarification-as-final-response
  path byte-for-byte unchanged (regression).
- mcpo path: outer LLM cannot accidentally call resume tools.

### S8. CLI auto-loop needs a guard

Text-mode CLI auto-loop must enforce the per-run prompt cap from S3 and
also a wall-clock cap, otherwise a buggy or adversarial model can hang the
operator's terminal indefinitely.

### S9. `interactive=True` is asymmetric

If a client sends `interactive=True` but the model never calls `ask_user`,
the protocol degrades to current behaviour, which is fine. Make this
explicit in the doc; otherwise readers may assume the flag changes other
behaviour (e.g. verification gaps).

## Recommended answers to the open questions

(The doc lists open questions; my recommendations:)

1. **Single vs multi pending prompt** -> single per session for v1
   (enforce via M3).
2. **Prompt TTL default** -> 10 minutes, configurable via
   `GOFR_AGENT_PENDING_PROMPT_TTL_SECONDS`.
3. **Identity binding** -> required (M5); without it the feature ships
   only behind a `--allow-unauthenticated-resume` dev flag.
4. **Notifications during pause** -> none; clients poll
   `get_pending_user_input` for recovery (M8).
5. **Compose with `requires_approval`** -> out of scope for v1; follow-up.

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Hijack of paused run via guessed prompt/session id | Medium | High | M5: CSPRNG prompt_id, subject binding |
| Token-downgrade across resume | Medium | High | M6: explicit policy |
| Message-history corruption on expiry/cancel | High | Medium | M4: sanitisation step |
| Resume runs on wrong replica | Medium | High in clustered deploys | M7: document single-replica constraint |
| Model traps user in question loop | Medium | Medium | S3: per-run prompt cap |
| Backward-compat break for clients ignoring `status` | Low | Medium | S1: do not put prompt in `answer` |
| pydantic-ai resume contract drift | Medium | High | M2: verify against current `_agent_graph.py` before coding |
| Reinventing MCP elicitation | Already done | Reputational | M1: address in doc |

## Concrete edits to apply to the strategy doc

1. Add an "Alternatives considered" section covering MCP `ctx.elicit()`,
   SSE side channel, and the `/agent/ask/respond` HTTP route from
   `docs/react_integration_guide.md` section 5b. Justify the chosen
   approach.
2. Replace the resume code snippet with a version that uses
   `all_messages()` and no synthetic user prompt, with an inline citation
   of the pydantic-ai code path.
3. Add a "Single-replica constraint" callout near the top.
4. Add a "Message-history sanitisation on cancel/expiry" sub-section
   referencing `pydantic_ai/ui/_adapter.py:sanitize_messages`.
5. Tighten security notes: prompt_id entropy, constant-time comparison,
   subject binding, token-downgrade policy, bounded prompt size,
   prompt-budget per run.
6. Split Phase 1 into 1A (deterministic) and 1B (deferred-tool engine).
7. Either drop the custom MCP tools in favour of MCP elicitation, or
   explicitly justify keeping them.
8. Mark the new MCP tools as model-hidden.
9. Add the test-plan section enumerating S7 cases.
10. Replace the example response where `answer` carries prompt text; set
    `answer` empty under `waiting_for_user`.

## What is fine to keep

1. Overall opt-in `interactive=true` shape on `ask`.
2. Activity-per-tool authorization pattern.
3. New event kinds list and shared field convention.
4. The deterministic-clarification-to-prompt conversion (modulo splitting
   into Phase 1A).
5. Phase 0 (use existing `clarification_request` while server work is in
   flight).
6. Goals 1-6 as stated.

## Verdict

Revise the strategy doc and re-circulate. Do not start an implementation
plan or code until Major issues 1-8 are settled and a reviewer with
operational ownership of auth and React UI signs off.
