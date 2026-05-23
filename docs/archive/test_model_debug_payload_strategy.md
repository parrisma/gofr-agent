# Test Model Debug Payload Strategy

## Symptom

The React UI receives a response shaped like a large JSON object keyed by tool
names, with values wrapped in `<<BEGIN_TOOL_DATA>>` sentinel blocks.

## Hypothesized Root Cause

`scripts/start-real-server.sh` defaults `MODEL` to `test` when
`GOFR_AGENT_LLM_MODEL` is unset. The pydantic-ai test model is designed for
testing tool plumbing, not for user-facing answers. With many registered tools,
it can return a map of tool names to raw tool return strings. That makes the UI
look like it is receiving a debug payload regardless of the downstream failure
message.

## Validation

- The pasted payload contains raw `<<BEGIN_TOOL_DATA>>` tool return wrappers.
- Those wrappers are produced by `app/agent/tool_factory.py` for model-internal
  tool transport.
- The failing server command did not include `--model` or `--llm-model`.
- The launcher default is currently `test`.

## Fix

Make the real-server launcher default to the repository's OpenRouter model and
reserve `--llm-model test` for explicit plumbing/debug runs.