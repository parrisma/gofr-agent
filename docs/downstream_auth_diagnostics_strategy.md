# Downstream Auth Diagnostics Strategy

## Symptom

User prompts reach `GoFRAgentAsk` successfully, but downstream MCP tool calls return authorization errors to the UI while the server logs show only a completed agent run.

## Hypothesized Root Cause

The agent treats downstream authorization failures as non-fatal tool results. This keeps the reasoning run alive, but the denial is not logged at the point where the required downstream activity is checked. The final run log also lacks tool error counters, so `Agent run completed` can obscure that every attempted downstream tool call failed authorization.

## Confirmed Root Cause

The real server entrypoint constructed the MCP server with the configured auth service, but constructed `GofrAgent` without passing that same auth service. As a result, top-level `GoFRAgentAsk` authorization used the configured development auth service, while downstream tool authorization inside the agent fell back to `FailClosedAuthService` and denied every `MCPServer*` activity.

## Assumptions And Validation

- Top-level MCP auth is already logged in `app/mcp_server/mcp_server.py`.
- Downstream auth is checked inside `app/agent/tool_factory.py` before opening a user downstream session.
- A caller token may be authorized for `GoFRAgentAsk` but not for `MCPServer*` or a specific downstream activity.
- Diagnostics must not log raw bearer tokens or secrets.

## Diagnostics Order

1. Log downstream auth denials at the tool wrapper with service, tool, required activity, outcome, error class, request id, and a non-secret credential fingerprint.
2. Keep returning structured non-fatal tool results so partial answers can still work.
3. Add stable error codes for downstream auth failures so UI and tests can distinguish auth from generic tool failure.
4. Add final run counters for tool calls, tool results, tool errors, and tool auth denials.
5. Mark the final run outcome as auth-denied when every tool result failed for downstream auth.