# Downstream Tool Contract Strategy

Status: Resolved. Downstream JSON schemas are preserved, local validation and
retry prompts are implemented, and descriptor-enabled large-result handoff is
handled by the results hub path. The broader downstream contract also includes
prompt-shaping capability metadata such as descriptions, visibility flags, and
any MCP `instructions`-style text that can behave like a soft system prompt if
surfaced to the model.

## Symptom

The agent can call downstream tools with malformed argument payloads, including
missing required fields, because the wrapper layer does not expose the
downstream tool's JSON schema as the actual agent-side tool contract.

The original strategy also described the downstream contract too narrowly.
Schema is only the executable part. Downstream services can also expose
capability metadata, such as tool descriptions or MCP/server `instructions`,
that may shape model behaviour if passed through verbatim.

## Hypothesised Root Cause

`app/agent/tool_factory.py` currently wraps every downstream tool with a
generic `async def _call(ctx, **kwargs)` function and builds a `Tool` from that
signature. That collapses the advertised tool schema to an empty object,
leaving required arguments and field structure hidden from the model.

At the same time, the contract boundary was framed as `input_schema` only.
That leaves prompt-shaping capability fields without an explicit policy,
despite the fact that `description`, `modelVisible`, and future
`instructions`-style capability text can influence the model in ways that feel
similar to a system prompt.

## Assumptions And Validation

- Assumption: downstream MCP `input_schema` is the source of truth for each
  tool contract.
- Assumption: the downstream contract has two layers: the executable call
  contract (`input_schema`) and prompt-shaping capability metadata
  (`description`, visibility flags, and any discovered `instructions`-style
  fields).
- Assumption: exposing that schema through `Tool.from_schema(...)` will give the
  model a clear contract.
- Assumption: validating tool-call kwargs locally against the same JSON schema
  and raising `ModelRetry` will make the agent repair malformed calls instead of
  passing them downstream.
- Assumption: downstream capability metadata can act like a soft system prompt
  if rendered naively, so it must be treated as untrusted metadata rather than
  authoritative instructions.
- Assumption: only the agent's own system prompt and authenticated requester
  `instructions` are authoritative behaviour-shaping inputs.
- Validation: add unit tests proving `make_tool()` exposes the downstream JSON
  schema and rejects malformed arguments that violate required fields or schema
  constraints.
- Validation: document and test that prompt-shaping downstream metadata is
  quoted, bounded, and framed as capability text only, and that future
  downstream `instructions`-style fields follow the same rule.

## Diagnostics Order

1. Confirm `make_tool()` currently emits an empty `{type: object, properties: {}}`
   schema regardless of downstream `input_schema`.
2. Update the wrapper to preserve downstream schema verbatim.
3. Add local schema validation for tool-call kwargs before execution.
4. Audit prompt-shaping downstream metadata separately from executable schema,
  including `description`, `modelVisible`, and any MCP/server
  `instructions`-style capability fields.
5. Ensure those metadata fields are treated as capability text only and cannot
  override the system prompt or authenticated requester instructions.
6. Run focused unit tests for `app.agent.tool_factory` and the related prompt
  assembly / hardening surfaces.

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

## Expanded Contract Definition

The downstream tool contract should be read as two separate layers:

1. Executable contract: JSON `input_schema`, required and optional arguments,
   descriptor argument handling, and result-handoff conventions.
2. Prompt-shaping capability metadata: tool descriptions, visibility flags, and
   any discovered MCP `instructions`-style text that may influence the model if
   surfaced in prompt-adjacent contexts.

The enforcement posture is different for each layer:

- Preserve the executable contract verbatim for tool construction, local
  validation, and retry guidance.
- Treat prompt-shaping capability metadata as untrusted metadata only. Quote,
  bound, and neutralise it rather than treating it as authoritative guidance.
- Never allow downstream capability metadata to override the system prompt,
  developer policy, or authenticated requester `instructions`.
- If gofr-agent later ingests downstream server-level `instructions` during MCP
  discovery or initialisation, handle that field under the same untrusted
  capability-metadata policy rather than promoting it into the authoritative
  prompt layer.