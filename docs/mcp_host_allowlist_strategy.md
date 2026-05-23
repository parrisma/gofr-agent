## Symptom

The GOFR-Agent UI can reach the runtime container, but `/mcp` requests fail because FastMCP rejects the inbound `Host` header.

## Hypothesized Root Cause

- The compose runtime launcher inherits a stale exported `GOFR_AGENT_MCP_ALLOWED_HOSTS` value from the shell.
- That stale value omits current runtime aliases such as `gofr-agent-runtime` and omits bare loopback host values such as `localhost`.
- As a result, the running container does not receive the intended allowlist even though newer defaults exist in the compose file.

## Assumptions To Validate

- The live `gofr-agent-runtime` container environment differs from the current compose file defaults.
- The inherited shell environment contains the stale host allowlist.
- Broadening the canonical defaults to include bare loopback hosts is safe and consistent with FastMCP host-header matching.

## Diagnostics Order

1. Inspect the live container environment for `GOFR_AGENT_MCP_ALLOWED_HOSTS`, `GOFR_AGENT_MCP_ALLOWED_ORIGINS`, and `GOFR_AGENT_CORS_ORIGINS`.
2. Compare the live values with the current compose and script defaults.
3. Patch the canonical defaults and launcher scripts so legacy inherited defaults are upgraded automatically.
4. Validate configuration parsing and launcher behavior with targeted tests.