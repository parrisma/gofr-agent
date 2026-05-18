# CLI Max Steps Override Strategy

## Symptom

`scripts/start-real-server.sh` starts the server with `GOFR_AGENT_MAX_STEPS=50`, but real requests still fail with `UsageLimitExceeded` reporting `tool_calls_limit of 10`.

## Hypothesized Root Cause

The server default is not the only source of `max_steps`.

`app/cli/ask.py` defines `--max-steps` with a client-side default of `10` and always includes `"max_steps": max_steps` in the `ask` request payload. That means callers using the CLI override the server default on every request unless they explicitly pass another value.

## Assumptions And Validation

- Verified server behavior: `app/mcp_server/mcp_server.py` resolves `config.max_steps` only when the incoming request omits `max_steps`.
- Verified agent behavior: `app/agent/agent.py` passes the resolved `max_steps` directly to `UsageLimits(tool_calls_limit=max_steps)`.
- Verified client override: `app/cli/ask.py` currently defaults `max_steps` to `10` and always sends it.

These observations explain the reported mismatch: server banner shows `50`, request still runs with `10`.

## Diagnostics Order

1. Change CLI `--max-steps` to be optional instead of defaulting to `10`.
2. Only include `max_steps` in request params when the user explicitly sets it.
3. Update unit tests to cover both explicit and omitted `--max-steps` cases.
4. Run targeted tests for the CLI path.