# gofr-agent — Integration Guide for a React Front-End

Audience: an LLM coding assistant working in a separate React/TypeScript
codebase that needs to add a "chat with the reasoning agent" capability,
including showing step-by-step reasoning and (eventually) collecting user
input mid-run.

This document describes:

1. What gofr-agent is and how it is exposed today.
2. The exact wire protocol the React app must speak (MCP Streamable HTTP).
3. The `ask` tool: inputs, outputs, session semantics, auth.
4. What is and is **not** currently supported (live reasoning notifications
  are supported; mid-run user input is not).
5. The current reasoning-notification contract plus one remaining
  recommended extension (interactive "ask the user" pause/resume).
6. Reference TypeScript snippets the React-side LLM can adapt directly.

---

## 1. What gofr-agent is

gofr-agent is an MCP (Model Context Protocol) server that wraps a
`pydantic-ai` reasoning agent. The agent is configured with a set of
downstream MCP services (e.g. `instruments`, `clients`, `trades`,
`analytics`) and decides which of their tools to call to answer a user's
question. Each call is one "step" in its reasoning loop.

Key facts:

- Transport: **MCP Streamable HTTP** (single endpoint, default `/mcp`).
- Default URL inside the dev container: `http://gofr-agent:8090/mcp`.
- Browser clients need whatever externally reachable origin the deployment
  exposes; inside the Docker dev network, use the `gofr-agent` service name.
- LLM backend: configurable. Default in dev: `deepseek/deepseek-v4-pro`
  via OpenRouter.
- Auth: Bearer token in the `Authorization` HTTP header. Required on
  every request. Dev token is `dev-admin-token`.
- Sessions: server-side conversation history keyed by `session_id`
  (UUID-like string chosen by the client). TTL is 60 minutes idle.

---

## 2. Wire protocol — MCP Streamable HTTP

The React app should **not** roll its own JSON-RPC client. Use the
official TypeScript MCP SDK:

- Package: `@modelcontextprotocol/sdk`
- Client class: `Client`
- Transport class: `StreamableHTTPClientTransport`

Minimum example (works in modern browsers and Node):

```ts
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

const transport = new StreamableHTTPClientTransport(
  new URL("http://gofr-agent:8090/mcp"),
  {
    requestInit: {
      headers: { Authorization: `Bearer ${token}` },
    },
  },
);

const client = new Client(
  { name: "gofr-agent-react-ui", version: "0.1.0" },
  { capabilities: {} },
);

await client.connect(transport);
await client.setLoggingLevel("info");

client.setNotificationHandler("notifications/message", notification => {
  const payload = notification.params?.data;
  if (!payload || typeof payload !== "object") return;
  if ((payload as { kind?: unknown }).kind === undefined) return;
  const logger = notification.params?.logger;
  if (logger !== "gofr-agent.reasoning") return;

  // Append payload to your active turn's reasoning trace.
  console.log("reasoning event", payload);
});
```

Once connected, the React app calls server-side tools by name:

```ts
const result = await client.callTool({
  name: "ask",
  arguments: {
    question: "Question text",
    session_id: "ui-session-1",
    max_steps: 25,
  },
});
```

The MCP `callTool` response is a `CallToolResult` with a `content` array.
gofr-agent always returns a single `TextContent` whose `.text` field is a
JSON string — parse it to get the structured result described below.

While `ask` is running, gofr-agent emits MCP logging notifications. For
reasoning events, the notification method is `notifications/message`, the logger
is `gofr-agent.reasoning`, and the notification `data` field is the event
payload described below.

CORS: the gofr-agent process is `uvicorn` + Starlette. If the React app
is served from a different origin, the operator must add a CORS
middleware to allow the browser origin and the `Authorization` header.
This is a deployment task; flag it to the operator if needed.

---

## 3. The tools exposed by gofr-agent

All tools require the `Authorization: Bearer <token>` header. The dev
token grants every activity below.

### `ping`
- Args: none.
- Returns: `{ status: "ok", timestamp: <ISO8601>, version: <str> }`.
- Use for: connectivity check on app start.

### `list_services`
- Args: none.
- Returns: array of `{ name, status, tools: [{ name, description }] }`.
- Use for: showing the user which downstream capabilities exist.

### `ask` — the main tool
- Args:
  - `question` (string, required): the user's natural-language question.
  - `session_id` (string, optional): client-chosen ID. If omitted, the
    server generates one and returns it. Reuse the same ID for follow-up
    turns to keep conversation context.
  - `context` (string, optional): extra free-text context prepended to
    the question.
  - `max_steps` (int, optional, default 10): hard cap on tool-call
    iterations the agent is allowed for this question. Increase for
    complex multi-service questions (20–30 is typical).
  - `model_override` (string, optional): allow-listed model override.
    The caller must also hold `AGENT_MODEL_OVERRIDE`.
- Returns:
  ```json
  {
    "session_id": "ui-session-1",
    "request_id": "req-123",
    "answer": "final natural-language answer",
    "steps": [
      {"kind": "run_started", "sequence": 1},
      {"kind": "run_completed", "sequence": 7}
    ],
    "model": "deepseek/deepseek-v4-pro",
    "tokens_used": 1234
  }
  ```
- **Important**: `ask` still returns its final response only once the run has
  finished, but the server now emits live reasoning notifications during the
  run. `steps` is a compact non-text subset derived from that same event
  sequence. Tool-using runs and summary-compaction runs produce non-empty
  `steps`.

### `reset_session`
- Args: `{ session_id: string }`.
- Returns: `{ status: "ok", session_id }`.
- Use for: a "Clear conversation" button.

### `register_service`
- Args: `{ name, url, token?, description? }`.
- Returns: `{ status: "registered", name, tools_discovered: <int> }`.
- Policy: requires runtime registration to be enabled server-side and the target
  host to match `allowed_service_hosts`.
- Use for: admin UI only. Most React apps will not need this.

### `refresh_services`
- Args: none.
- Use for: admin UI only.

---

## 4. Current limitations the React-side LLM must understand

The brief mentions two desired UX features:

1. **Show step-by-step reasoning as it happens.**
2. **Allow the user to provide additional input mid-run.**

The first is supported; the second is not. Specifically:

- `ask` is still a single request/response for the final payload, but the
  server emits live MCP reasoning notifications while the run is in flight.
  Clients that ignore notifications can still rely on the final response.
- The agent has no "human-in-the-loop" mechanism. Once `ask` is in
  flight, there is no protocol to send extra input to the running run
  short of cancelling and starting over with a more detailed prompt
  (which loses partial work).

**The React-side LLM should not invent client-side workarounds for
mid-run input.** Do not fake pause/resume semantics that the server does not
support.

What the React app **can** do today, with no server changes:

- Render a normal chat UI: input box, list of turns, send button.
- Subscribe to reasoning notifications and render a live reasoning panel.
- Show a spinner while `ask` is running.
- Persist `session_id` per chat thread and reuse it across turns.
- Provide a "Reset" button that calls `reset_session`.
- Expose a "max steps" advanced setting (default 10, raise for complex
  queries).
- Surface `request_id`, `tokens_used`, and `model` from the response as
  metadata.
- Catch MCP `McpError` and show the `.message` to the user. Common
  cases: missing/invalid token (`INVALID_PARAMS`), `tool_calls_limit`
  exceeded (raise `max_steps`).

---

## 5. Current reasoning notification contract and remaining extension

### 5a. Live reasoning notifications (current)

The server now emits reasoning events as MCP logging notifications while
`ask` runs.

Notification contract:

- MCP notification type: logging/message.
- Logger: `gofr-agent.reasoning`.
- Payload: `params.data` is the event object.
- Correlation: each event includes the same `request_id` returned by the final
  `ask` response.

Event kinds currently emitted:

| `kind` | Meaning |
|--------|---------|
| `run_started` | The `ask` run has started |
| `step_started` | A logical reasoning/tool step has started |
| `text_delta` | Incremental model text |
| `tool_call` | The model requested a downstream tool |
| `tool_retry` | A transient tool failure is being retried |
| `tool_result` | A downstream tool completed |
| `summary_update` | Older session history was compacted into the rolling summary |
| `step_completed` | A logical step finished |
| `run_completed` | The run finished successfully |
| `run_failed` | The run failed before completion |

The final `steps` array in the `ask` response is derived from the same event
sequence, excluding `text_delta` events.

Shared fields on every event:

| Field | Meaning |
|-------|---------|
| `request_id` | Correlates the run across notifications, logs, and final response |
| `session_id` | Conversation session id |
| `event_id` | Unique event id |
| `sequence` | Monotonic event order |
| `kind` | Event type |
| `timestamp` | UTC timestamp |

Important payload fields by kind:

| `kind` | Additional fields |
|--------|-------------------|
| `tool_call` | `service`, `tool`, `arguments`, `attempt` |
| `tool_retry` | `service`, `tool`, `attempt`, `message` |
| `tool_result` | `service`, `tool`, `ok`, `summary`, `attempt`, `latency_ms`, `truncated` |
| `summary_update` | `summary` |
| `run_completed` | `model`, `answer_preview`, `tokens_used` |
| `run_failed` | `error`, `fatal` |

### 5b. Human-in-the-loop input

This is still not implemented. If you need it, request a server-side extension.

One reasonable direction is a future notification type such as:

| `event:` | `data:` payload                                                     |
|----------|---------------------------------------------------------------------|
| `prompt` | `{ prompt_id, question, schema?: JSONSchema, choices?: string[] }`  |

The UI would show the question to the user and then send a follow-up response
back to the server.

One possible API shape:

```
POST /agent/ask/respond
  body: { session_id, prompt_id, value }
  headers: Authorization: Bearer <token>
```

---

## 6. Reference TypeScript snippets

### Chat hook (today's API — final response plus notifications)

This snippet shows both the notification subscription and the final-response
path using the MCP TypeScript SDK's `setNotificationHandler` API.

```ts
import { useState, useCallback, useRef } from "react";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

type Turn = { role: "user" | "agent"; text: string };

export function useGofrAgent(opts: { url: string; token: string }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [events, setEvents] = useState<Record<string, unknown[]>>({});
  const sessionId = useRef(crypto.randomUUID());
  const clientRef = useRef<Client | null>(null);

  const ensureClient = useCallback(async () => {
    if (clientRef.current) return clientRef.current;
    const transport = new StreamableHTTPClientTransport(new URL(opts.url), {
      requestInit: { headers: { Authorization: `Bearer ${opts.token}` } },
    });
    const client = new Client(
      { name: "gofr-agent-react-ui", version: "0.1.0" },
      { capabilities: {} },
    );
    await client.connect(transport);
    await client.setLoggingLevel("info");
    client.setNotificationHandler("notifications/message", notification => {
      if (notification.params?.logger !== "gofr-agent.reasoning") return;
      const payload = notification.params?.data;
      if (!payload || typeof payload !== "object") return;
      const event = payload as { request_id?: string };
      const requestId = event.request_id ?? "pending";
      setEvents(prev => ({
        ...prev,
        [requestId]: [...(prev[requestId] ?? []), payload],
      }));
    });
    clientRef.current = client;
    return client;
  }, [opts.url, opts.token]);

  const ask = useCallback(async (question: string, maxSteps = 20) => {
    setTurns(t => [...t, { role: "user", text: question }]);
    setBusy(true);
    try {
      const client = await ensureClient();
      const res = await client.callTool({
        name: "ask",
        arguments: {
          question,
          session_id: sessionId.current,
          max_steps: maxSteps,
        },
      });
      const text = (res.content?.[0] as { text?: string })?.text ?? "{}";
      const data = JSON.parse(text) as {
        request_id: string;
        answer: string;
      };
      setTurns(t => [...t, { role: "agent", text: data.answer }]);
    } finally {
      setBusy(false);
    }
  }, [ensureClient]);

  const reset = useCallback(async () => {
    const client = await ensureClient();
    await client.callTool({
      name: "reset_session",
      arguments: { session_id: sessionId.current },
    });
    setTurns([]);
  }, [ensureClient]);

  return { turns, events, busy, ask, reset };
}
```

The older SSE-based sketch is obsolete. The current server streams reasoning
over MCP logging notifications, not over a parallel SSE endpoint.

---

## 7. Suggested phased implementation for the React project

Phase 1 — shipped server capabilities:

1. Add a settings panel with `url`, `token`, `max_steps`.
2. Implement the chat hook from §6.
3. On mount, call `ping` then `list_services`; show the latter in a
   collapsible "Capabilities" panel so the user can see what data the
   agent has access to.
4. Register a logging-notification handler and render incoming reasoning
   events as a collapsible trace under the active turn.
5. Show a spinner while `ask` is in flight.
6. Render `request_id`, `tokens_used`, and `model` as metadata under each
   agent turn.

Phase 2 — once §5b (human-in-the-loop) is delivered server-side:

7. Add a `<PromptModal>` rendered when `prompt` arrives; resolve its
   promise with the user's answer to unblock the run.
8. Persist the prompt history alongside the steps so a turn replay
    shows the full interaction.

---

## 8. Things the React-side LLM should ASK the user before coding

- Where will the React app run (browser? Electron?) and what origin?
  This determines whether CORS must be configured on gofr-agent.
- Which token will the app use? Dev (`dev-admin-token`) or a per-user
  token issued by an existing auth flow?
- Is Phase 1 acceptable as the first deliverable, or must Phases 2/3
  ship at the same time (in which case server-side work in §5 must be
  scheduled first)?
- Should the chat history persist across browser reloads? If yes, only
  the `session_id` and the locally rendered turns need to be stored —
  the server keeps the model-side history under that ID.
