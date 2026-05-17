# Reasoning Stream Sequence Diagram

Status date: 2026-05-17.

This document shows the current interaction shape for `gofr-agent` reasoning
streams. The public transport is MCP Streamable HTTP. Live progress is delivered
as MCP `notifications/message` entries with logger `gofr-agent.reasoning`; the
final tool response is returned by `ask` or `respond_to_user_input` after the
run completes or pauses.

Result handoff between MCP services is mediated by the gofr-agent results hub.
Services do not pass large payloads directly to each other through the model.

## Startup, discovery, and hub registration

At startup, the service registry connects to configured downstream MCP services,
discovers tools, and optionally registers gofr-agent as the results hub for
services that expose `_register_results_hub`.

~~~mermaid
sequenceDiagram
   autonumber
   participant Agent as gofr-agent MCP server
   participant Registry as ServiceRegistry
   participant Pool as SessionPool
   participant Service as Downstream MCP service

   Agent->>Registry: load services.yml / env manifest
   loop Each enabled service
      Registry->>Pool: start service session pool
      Pool->>Service: initialize MCP session
      Registry->>Service: list tools
      Service-->>Registry: tool descriptors

      alt Hub enabled and service exposes _register_results_hub
         Registry->>Service: _register_results_hub(protocol_version, hub_url, tools, limits)
         alt Accepted
            Service-->>Registry: can_publish, can_consume, result_types
            Registry-->>Agent: store safe hub capabilities
         else Rejected or invalid response
            Service-->>Registry: rejection or malformed response
            Registry-->>Agent: store registration_error and continue degraded
         end
      else Hub disabled or service has no registration tool
         Registry-->>Agent: supports_results_hub=false
      end
   end
~~~

The model-facing tool list filters reserved hub tools such as
`_register_results_hub`, `_store_result`, `_get_result`, and `_describe_result`.
`list_services` may display safe capability fields, but never callback tokens.

## Normal `ask` run with live reasoning events

The caller invokes the MCP `ask` tool. The server validates auth and request
limits, creates or reuses a session, rejects a new request if that session has
unexpired pending user input, then starts the agent run.

~~~mermaid
sequenceDiagram
   autonumber
   participant Caller as MCP client / UI / CLI
   participant Agent as gofr-agent MCP server
   participant Store as SessionStore
   participant Reasoner as GofrAgent
   participant ServiceA as MCP service A
   participant ServiceB as MCP service B
   participant Hub as gofr-agent results hub tools

   Caller->>Agent: ask(question, session_id?, constraints?, interactive?)
   Agent->>Agent: require GoFRAgentAsk and validate payload
   opt model_override provided
      Agent->>Agent: require GoFRAgentModelOverride and allow-list model
   end
   Agent->>Store: get_or_create(session_id)
   Store-->>Agent: session
   Agent->>Store: get_pending_user_input(session_id)
   alt Unexpired pending prompt exists
      Agent-->>Caller: MCP INVALID_PARAMS session has pending user input
   else No pending prompt or expired prompt cleared
      Agent->>Reasoner: run(question, session, constraints, max_steps, interactive)
      Reasoner-->>Caller: notification run_started

      loop Model thought step
         Reasoner-->>Caller: notification step_started(step_kind=thought)
         Reasoner-->>Caller: notification text_delta
         Reasoner-->>Caller: notification step_completed(step_kind=thought)
      end

      loop Downstream tool step
         Reasoner-->>Caller: notification step_started(step_kind=tool_call)
         Reasoner-->>Caller: notification tool_call(service, tool, arguments)
         Reasoner->>ServiceA: service tool call

         opt Service publishes a large result to the hub
            ServiceA->>Hub: _store_result(callback token, payload, metadata, ttl)
            Hub-->>ServiceA: descriptor kind=gofr.result_ref
            ServiceA-->>Reasoner: descriptor or bounded summary
         end

         opt Consumer service needs descriptor payload
            Reasoner->>ServiceB: tool call with descriptor argument
            ServiceB->>Hub: _get_result or _describe_result(callback token, descriptor)
            Hub-->>ServiceB: payload or metadata
            ServiceB-->>Reasoner: derived result or bounded summary
         end

         alt Transient downstream failure retried
            Reasoner-->>Caller: notification tool_retry(service, tool, attempt)
            Reasoner->>ServiceA: retry service tool call
         end

         Reasoner-->>Caller: notification tool_result(summary, ok, latency, provenance refs)
         Reasoner-->>Caller: notification step_completed(step_kind=tool_result)
      end

      opt Session history exceeded raw-message window
         Reasoner->>Store: append messages and compact older history
         Reasoner-->>Caller: notification summary_update
      end

      alt Run completed
         Reasoner-->>Caller: notification run_completed(model, answer_preview, tokens_used)
         Reasoner-->>Agent: AgentResult(status=completed, answer, steps, provenance?)
         Agent-->>Caller: ask response JSON with answer, steps, status, is_complete
      else Run failed before completion
         Reasoner-->>Caller: notification run_failed(error, fatal=true)
         Reasoner-->>Agent: raises runtime, timeout, auth, or model/tool error
         Agent-->>Caller: MCP error response
      else Max steps reached with verification gaps enabled
         Reasoner-->>Caller: notification run_completed(reason=max_steps_reached)
         Reasoner-->>Agent: AgentResult with verification_gap
         Agent-->>Caller: ask response JSON with verification_gap
      end
   end
~~~

The `steps` array in the final response is derived from the same event stream,
excluding `text_delta` events and capped by `GOFR_AGENT_MAX_RESPONSE_STEPS`.
Individual event payload fields are truncated by
`GOFR_AGENT_MAX_EVENT_PAYLOAD_CHARS`; protected provenance fields such as
`service`, `tool`, `args_hash`, `artifact_id`, `as_of`, and `request_id` are
preserved.

## Interactive Phase 1A pause and resume

Interactive mode is available through `ask(interactive=true)` or
`GOFR_AGENT_INTERACTIVE_DEFAULT=true`, but it is accepted only when
`GOFR_AGENT_ALLOW_UNAUTHENTICATED_RESUME=true` in the current implementation.
Without that flag, the server rejects interactive requests before running the
agent.

When prompt-hardening verification gaps are enabled and deterministic missing
fields are detected, the agent can pause instead of returning a final
clarification answer. The pending prompt is stored in the session and resumed by
calling `respond_to_user_input`.

~~~mermaid
sequenceDiagram
   autonumber
   participant Caller as MCP client / UI / CLI
   participant Agent as gofr-agent MCP server
   participant Store as SessionStore
   participant Reasoner as GofrAgent

   Caller->>Agent: ask(question, session_id, interactive=true)
   Agent->>Agent: validate interactive resume configuration
   Agent->>Store: get_or_create(session_id)
   Agent->>Reasoner: run(..., interactive=true)

   alt Missing fields detected before model run
      Reasoner-->>Caller: notification user_input_requested(prompt_id, prompt, missing_fields)
      Reasoner-->>Caller: notification run_paused(prompt_id)
      Reasoner-->>Agent: AgentResult(status=waiting_for_user, is_complete=false)
      Agent->>Store: set_pending_user_input(session_id, prompt_id, resume_payload)
      Agent-->>Caller: ask response JSON with user_input_request
   else No missing fields
      Reasoner-->>Caller: normal reasoning notifications
      Reasoner-->>Agent: AgentResult(status=completed)
      Agent-->>Caller: ask response JSON with final answer
   end

   opt Client reconnects or refreshes before answering
      Caller->>Agent: get_pending_user_input(session_id, prompt_id?)
      Agent->>Store: get_pending_user_input(session_id)
      alt Pending prompt is live
         Agent-->>Caller: status=waiting_for_user, user_input_request
      else Missing, mismatched, or expired
         Agent-->>Caller: status=not_found or expired
      end
   end

   alt User answers prompt
      Caller->>Agent: respond_to_user_input(session_id, prompt_id, value)
      Agent->>Store: pop_pending_user_input(session_id, prompt_id)
      Agent-->>Caller: notification user_input_received(prompt_id)
      Agent-->>Caller: notification run_resumed(prompt_id)
      Agent->>Reasoner: run(resumed question, original constraints, interactive=false)
      Reasoner-->>Caller: normal reasoning notifications
      Reasoner-->>Agent: AgentResult(status=completed or failed)
      Agent-->>Caller: respond_to_user_input response JSON
   else User cancels prompt
      Caller->>Agent: cancel_user_input(session_id, prompt_id, reason?)
      Agent->>Store: clear_pending_user_input(session_id, prompt_id)
      Agent-->>Caller: notification user_input_cancelled(prompt_id, reason)
      Agent-->>Caller: status=cancelled
   end
~~~

While a session has a live pending prompt, a fresh `ask` for that same
`session_id` is rejected with `INVALID_PARAMS`. The caller should either answer,
cancel, or let the prompt expire before sending another question in that
session.

## Event and response contract summary

Events are emitted as MCP logging notifications:

| Field | Value |
|-------|-------|
| MCP method | `notifications/message` |
| Logger | `gofr-agent.reasoning` |
| Payload | `params.data` |
| Correlation | `request_id`, `session_id`, optional `run_id` |

Current event kinds:

| Kind | Notes |
|------|-------|
| `run_started` | Normal model/tool run started |
| `step_started` | Logical thought/tool step started |
| `text_delta` | Streaming model text, excluded from final `steps` |
| `tool_call` | Includes `service`, `tool`, `arguments`, `attempt` |
| `tool_retry` | Emitted when a transient tool failure is retried |
| `tool_result` | Includes bounded `summary`, `ok`, latency, and provenance refs |
| `summary_update` | Session history compaction occurred |
| `step_completed` | Logical step finished |
| `run_completed` | Includes `model`, `answer_preview`, `tokens_used` |
| `run_failed` | Includes `error` and `fatal` |
| `user_input_requested` | Interactive prompt was created |
| `run_paused` | Interactive run paused on `prompt_id` |
| `user_input_received` | Resume value was accepted, value is not echoed |
| `run_resumed` | Resume run started |
| `user_input_cancelled` | Pending prompt was cancelled |

The final `ask` and `respond_to_user_input` payload has this shape:

```json
{
  "session_id": "session-1",
  "request_id": "req-1",
  "answer": "...",
  "steps": [],
  "model": "openai:gpt-4o-mini",
  "tokens_used": 0,
  "status": "completed",
  "is_complete": true,
  "run_id": "req-1",
  "user_input_request": null,
  "verification_gap": null,
  "clarification_request": null,
  "provenance": []
}
```

For a paused interactive run, `status` is `waiting_for_user`, `is_complete` is
`false`, `answer` is empty, and `user_input_request` contains `prompt_id`,
`run_id`, `session_id`, `prompt`, optional schema/choices, timestamps, and
`missing_fields`.

## Related implementation files

- MCP tool definitions and response shaping: [../app/mcp_server/mcp_server.py](../app/mcp_server/mcp_server.py)
- Reasoning event models: [../app/agent/events.py](../app/agent/events.py)
- Agent run loop: [../app/agent/agent.py](../app/agent/agent.py)
- Session and pending input store: [../app/sessions/store.py](../app/sessions/store.py)
- Results hub protocol models: [../app/hub/models.py](../app/hub/models.py)