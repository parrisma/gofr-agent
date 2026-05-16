# Downstream Tool Contract Strategy

## Symptom

The agent can call downstream tools with malformed argument payloads, including
missing required fields, because the wrapper layer does not expose the
downstream tool's JSON schema as the actual agent-side tool contract.

## Hypothesised Root Cause

`app/agent/tool_factory.py` currently wraps every downstream tool with a
generic `async def _call(ctx, **kwargs)` function and builds a `Tool` from that
signature. That collapses the advertised tool schema to an empty object,
leaving required arguments and field structure hidden from the model.

## Assumptions And Validation

- Assumption: downstream MCP `input_schema` is the source of truth for each
  tool contract.
- Assumption: exposing that schema through `Tool.from_schema(...)` will give the
  model a clear contract.
- Assumption: validating tool-call kwargs locally against the same JSON schema
  and raising `ModelRetry` will make the agent repair malformed calls instead of
  passing them downstream.
- Validation: add unit tests proving `make_tool()` exposes the downstream JSON
  schema and rejects malformed arguments that violate required fields or schema
  constraints.

## Diagnostics Order

1. Confirm `make_tool()` currently emits an empty `{type: object, properties: {}}`
   schema regardless of downstream `input_schema`.
2. Update the wrapper to preserve downstream schema verbatim.
3. Add local schema validation for tool-call kwargs before execution.
4. Run focused unit tests for `app.agent.tool_factory`.

## Follow-up Finding

After preserving the schema, the model still repeatedly called
`analytics__simple_return` with `{}` after receiving a large OHLCV result. This
shows a second boundary problem: large structured outputs should not have to be
copied through model text to satisfy a later tool contract.

## Follow-up Plan

1. Add per-run agent dependencies that carry the bearer token plus a structured
  tool-result scratchpad.
2. Store structured downstream tool results and the arguments used to fetch them.
3. Resolve missing required structured arguments from recent compatible tool
  artifacts before validation/execution.
4. Keep the public tool schema unchanged so the model still sees the downstream
  contract.
5. Add focused tests for artifact storage and auto-resolution of required
  arguments such as `bars`.