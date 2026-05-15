# gofr-agent — Integration Guide for a React Front-End

Audience: an LLM coding assistant working in a separate React/TypeScript
codebase that needs to add a "chat with the reasoning agent" capability,
including showing step-by-step reasoning and (eventually) collecting user
input mid-run.

This document describes:

1. What gofr-agent is and how it is exposed today.
2. The exact wire protocol the React app must speak (MCP Streamable HTTP).
3. The `ask` tool: inputs, outputs, session semantics, auth.
4. What is and is **not** currently supported (no live step streaming, no
   mid-run user input).
5. Two recommended server-side extensions (SSE step events, interactive
   "ask the user" pause/resume) the React-side LLM may request from the
   gofr-agent maintainer if richer UX is required.
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
- Default URL when proxied to a host browser: whatever the deployment
  exposes; typical local dev: `http://localhost:8090/mcp`.
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
  new URL("http://localhost:8090/mcp"),
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
- Returns:
  ```json
  {
    "session_id": "ui-session-1",
    "answer": "final natural-language answer",
    "steps": [],
    "model": "deepseek/deepseek-v4-pro",
    "tokens_used": 1234
  }
  ```
- **Important**: today, `steps` is always `[]` and the call is fully
  blocking — the HTTP response only arrives once the agent has finished.
  See section 4 for what this means for UX.

### `reset_session`
- Args: `{ session_id: string }`.
- Returns: `{ status: "ok", session_id }`.
- Use for: a "Clear conversation" button.

### `register_service`
- Args: `{ name, url, token?, description? }`.
- Returns: `{ status: "registered", name, tools_discovered: <int> }`.
- Use for: admin UI only. Most React apps will not need this.

### `refresh_services`
- Args: none.
- Use for: admin UI only.

---

## 4. Current limitations the React-side LLM must understand

The brief mentions two desired UX features:

1. **Show step-by-step reasoning as it happens.**
2. **Allow the user to provide additional input mid-run.**

Neither is supported by the current gofr-agent build. Specifically:

- `ask` is a single request/response; the server emits no incremental
  events while the agent is thinking. The `steps` field in the response
  is currently always empty, so even after-the-fact step inspection is
  not available without a server change.
- The agent has no "human-in-the-loop" mechanism. Once `ask` is in
  flight, there is no protocol to send extra input to the running run
  short of cancelling and starting over with a more detailed prompt
  (which loses partial work).

**The React-side LLM should not invent client-side workarounds for
these.** Showing fake "thinking..." steps, polling, or trying to
intercept the model output stream from the browser will not work —
that data does not leave the server today.

What the React app **can** do today, with no server changes:

- Render a normal chat UI: input box, list of turns, send button.
- Show a single in-progress spinner while `ask` is running.
- Persist `session_id` per chat thread and reuse it across turns.
- Provide a "Reset" button that calls `reset_session`.
- Expose a "max steps" advanced setting (default 10, raise for complex
  queries).
- Surface `tokens_used` and `model` from the response as metadata.
- Catch MCP `McpError` and show the `.message` to the user. Common
  cases: missing/invalid token (`INVALID_PARAMS`), `tool_calls_limit`
  exceeded (raise `max_steps`).

---

## 5. Recommended server-side extensions (request these from the gofr-agent maintainer)

These are the minimum API additions needed to deliver the two desired
UX features. The React-side LLM should not implement them; it should
**request** them and design the React UI assuming they will land in the
shape described below. If/when they ship, the React code can switch
over without rewriting the chat shell.

### 5a. Streaming step events (SSE)

Proposed new HTTP endpoint, parallel to the MCP endpoint:

```
GET  /agent/ask/stream?session_id=...&max_steps=...
POST /agent/ask/stream
       body: { question, session_id?, context?, max_steps? }
       headers: Authorization: Bearer <token>
       response: text/event-stream (SSE)
```

Event types the React app should expect to render:

| `event:` | `data:` payload (JSON)                                              | UI hint |
|----------|---------------------------------------------------------------------|---------|
| `start`  | `{ session_id, model }`                                             | Begin a new "thinking" panel |
| `step`   | `{ index, kind: "tool_call", service, tool, args }`                 | "Calling `clients.get_holdings({...})`" |
| `step`   | `{ index, kind: "tool_result", service, tool, result_preview }`    | Show truncated result under the call |
| `step`   | `{ index, kind: "thought", text }`                                  | Italicised line of model narration |
| `token`  | `{ text }`                                                          | Append to the streaming final-answer area |
| `done`   | `{ answer, tokens_used, steps }`                                    | Finalise and persist the turn |
| `error`  | `{ code, message }`                                                 | Show error toast, end stream |

Auth and `session_id` semantics are identical to the MCP `ask` tool.
The MCP `ask` tool should remain available unchanged for non-UI clients.

### 5b. Human-in-the-loop input

Add one extra event type plus one POST endpoint:

| `event:` | `data:` payload                                                     |
|----------|---------------------------------------------------------------------|
| `prompt` | `{ prompt_id, question, schema?: JSONSchema, choices?: string[] }`  |

When the React app receives a `prompt` event the SSE stream pauses
(keep the connection open). The UI shows the question to the user.
When the user answers, the React app POSTs:

```
POST /agent/ask/respond
  body: { session_id, prompt_id, value }
  headers: Authorization: Bearer <token>
```

The server resumes the run; subsequent `step` / `token` / `done`
events continue on the original SSE stream.

The agent side requires a new pydantic-ai tool, e.g. `ask_user(question,
schema?)`, that suspends the run on a `Future` keyed by `prompt_id`
until `/agent/ask/respond` resolves it.

---

## 6. Reference TypeScript snippets

### Chat hook (today's API — blocking `ask`)

```ts
import { useState, useCallback, useRef } from "react";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

type Turn = { role: "user" | "agent"; text: string };

export function useGofrAgent(opts: { url: string; token: string }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
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
      const data = JSON.parse(text) as { answer: string };
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

  return { turns, busy, ask, reset };
}
```

### SSE consumer (when 5a/5b ship)

```ts
async function streamAsk(opts: {
  url: string;             // e.g. http://localhost:8090/agent/ask/stream
  token: string;
  question: string;
  sessionId: string;
  maxSteps?: number;
  onStart: (e: { session_id: string; model: string }) => void;
  onStep: (e: any) => void;
  onToken: (text: string) => void;
  onPrompt: (e: { prompt_id: string; question: string }) => Promise<unknown>;
  onDone: (e: { answer: string; tokens_used: number; steps: any[] }) => void;
  onError: (e: { code: string; message: string }) => void;
  signal?: AbortSignal;
}) {
  const resp = await fetch(opts.url, {
    method: "POST",
    signal: opts.signal,
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      Authorization: `Bearer ${opts.token}`,
    },
    body: JSON.stringify({
      question: opts.question,
      session_id: opts.sessionId,
      max_steps: opts.maxSteps ?? 20,
    }),
  });
  if (!resp.ok || !resp.body) {
    opts.onError({ code: String(resp.status), message: await resp.text() });
    return;
  }

  const reader = resp.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += value;
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const evtMatch = frame.match(/^event:\s*(.+)$/m);
      const dataMatch = frame.match(/^data:\s*(.+)$/m);
      if (!dataMatch) continue;
      const evt = evtMatch?.[1] ?? "message";
      const data = JSON.parse(dataMatch[1]);
      switch (evt) {
        case "start":  opts.onStart(data); break;
        case "step":   opts.onStep(data); break;
        case "token":  opts.onToken(data.text); break;
        case "prompt": {
          const value = await opts.onPrompt(data);
          await fetch(opts.url.replace("/stream", "/respond"), {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${opts.token}`,
            },
            body: JSON.stringify({
              session_id: opts.sessionId,
              prompt_id: data.prompt_id,
              value,
            }),
          });
          break;
        }
        case "done":  opts.onDone(data); return;
        case "error": opts.onError(data); return;
      }
    }
  }
}
```

---

## 7. Suggested phased implementation for the React project

Phase 1 — works against today's gofr-agent:

1. Add a settings panel with `url`, `token`, `max_steps`.
2. Implement the chat hook from §6 (blocking `ask`).
3. On mount, call `ping` then `list_services`; show the latter in a
   collapsible "Capabilities" panel so the user can see what data the
   agent has access to.
4. Show a single spinner per turn while `ask` is in flight.
5. Render `tokens_used` and `model` as metadata under each agent turn.

Phase 2 — once §5a (SSE step events) is delivered server-side:

6. Replace the chat hook's `ask` implementation with the SSE consumer
   from §6. Keep the same hook signature so call sites do not change.
7. Render incoming `step` events as a collapsible "reasoning trace"
   under the agent turn (tool name, args, truncated result).
8. Stream `token` events into the visible answer area.

Phase 3 — once §5b (human-in-the-loop) is delivered server-side:

9. Add a `<PromptModal>` rendered when `onPrompt` fires; resolve its
   promise with the user's answer to unblock the run.
10. Persist the prompt history alongside the steps so a turn replay
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
