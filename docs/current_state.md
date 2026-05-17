# gofr-agent Current State

Status date: 2026-05-17.

This document is the short current-state map for the repository. Older files in
`docs/` include implementation plans, review notes, and strategy documents; use
this page to understand what is implemented now and which docs are canonical for
each surface.

## Implemented runtime surfaces

| Surface | Current state | Canonical docs |
|---------|---------------|----------------|
| MCP server | FastMCP Streamable HTTP server exposes `ping`, `list_services`, `ask`, `reset_session`, `register_service`, `refresh_services`, and model-hidden hub tools. | [README.md](../README.md), [master_specification.md](master_specification.md) |
| Service registry | Loads YAML/env service manifests, discovers MCP tools, maintains per-service pools, continues in degraded mode when startup services fail, and supports guarded runtime registration. | [master_specification.md](master_specification.md), [archive/reasoning_stream_spec.md](archive/reasoning_stream_spec.md) |
| Reasoning stream | `ask` emits live MCP `notifications/message` events with logger `gofr-agent.reasoning`; final `steps` are derived from the same event stream. | [archive/reasoning_stream_spec.md](archive/reasoning_stream_spec.md), [react_integration_guide.md](react_integration_guide.md) |
| Human-in-the-loop Phase 1A | Deterministic pre-LLM missing-field prompts can pause with `status="waiting_for_user"`; MCP tools `respond_to_user_input`, `get_pending_user_input`, and `cancel_user_input` resume, recover, or clear process-local pending state. LLM-initiated prompts are still Phase 1B. | [human_in_the_loop_strategy.md](human_in_the_loop_strategy.md), [react_integration_guide.md](react_integration_guide.md) |
| Results hub | Process-local, in-memory descriptor handoff is implemented with `_register_results_hub`, `_store_result`, `_get_result`, `_describe_result`, callback-token principals, result-type enforcement, TTL, size bounds, and reserved-tool filtering. | [archive/mcp_artifact_handoff_spec.md](archive/mcp_artifact_handoff_spec.md), [archive/results_hub_mcp_server_spec.md](archive/results_hub_mcp_server_spec.md) |
| Prompt hardening | Hardened prompt, structured caller fields, intent constraints, grounding checks, verification gaps, clarifications, and provenance are implemented behind default-off config flags. | [prompt_hardening_strategy.md](prompt_hardening_strategy.md), [archive/prompt_hardening_implementation_plan.md](archive/prompt_hardening_implementation_plan.md), [prompt_hardening_test_plan.md](prompt_hardening_test_plan.md) |
| CLI | `app.cli.ask` supports text/json output, streaming event display, quiet/verbose modes, sessions, structured caller fields, runtime constraints, max steps, reset, and `--interactive` Phase 1A prompt resume. | [README.md](../README.md), [react_integration_guide.md](react_integration_guide.md) |
| Fixture chat | `scripts/fixture_chat.py` launches fixture services, a local gofr-agent MCP server, and a REPL for live/manual testing, including descriptor hub workflows. | [README.md](../README.md) |

## Current defaults and flags

Runtime defaults in `app/config.py` remain compatibility-preserving:

- `GOFR_AGENT_LLM_MODEL`: `openai:gpt-4o-mini`
- `GOFR_AGENT_HUB_ENABLED`: `false`
- `GOFR_AGENT_PROMPT_HARDENING_V2_ENABLED`: `false`
- `GOFR_AGENT_CALLER_CONTENT_STRUCTURED_ENABLED`: `false`
- `GOFR_AGENT_INTENT_CONSTRAINTS_ENABLED`: `false`
- `GOFR_AGENT_GROUNDING_ENFORCEMENT_ENABLED`: `false`
- `GOFR_AGENT_VERIFICATION_GAP_RESPONSE_ENABLED`: `false`
- `GOFR_AGENT_PROVENANCE_IN_RESPONSE_ENABLED`: `false`
- `GOFR_AGENT_INTERACTIVE_DEFAULT`: `false`
- `GOFR_AGENT_PENDING_PROMPT_TTL_SECONDS`: `600`
- `GOFR_AGENT_ALLOW_UNAUTHENTICATED_RESUME`: `false`

`GofrAgentConfig.from_env()` supports the full typed config. The
`app.main_mcp` command currently wires host, MCP port, services file, log
level, pool size, and model through CLI/env arguments; fixture chat and tests
construct richer config objects directly.

Fixture chat and live prompt-hardening smoke runs use
`deepseek/deepseek-v4-pro` by default in this repository because it worked in
the current OpenRouter environment where `openai/gpt-4o-mini` was region
blocked.

## Validation snapshot

Latest recorded prompt-hardening closeout:

- Focused completion slice: code-quality gate 6/6 and focused tests 28/28.
- Full wrapper: 154 passed, 12 skipped, 103 warnings.
- Live OpenRouter smoke during implementation: 3/3 passed on
  `deepseek/deepseek-v4-pro`.
- Full weak/mid/strong live matrix remains explicit cost/key opt-in via
  `GOFR_AGENT_LIVE_LLM_FULL_MATRIX=1`.

## Known caveats

- Sessions are in-memory and process-local.
- Pending human-input prompts are in-memory and process-local. Process restart
  loses pending prompts; multi-replica use needs sticky routing by
  `session_id` or a shared pending store.
- Phase 1A human-in-the-loop support is deterministic pre-LLM clarification
  only. LLM-initiated prompts using pydantic-ai deferred tools are not yet
  implemented.
- Resume is disabled by default unless subject-bound auth is added or
  `GOFR_AGENT_ALLOW_UNAUTHENTICATED_RESUME=true` is intentionally enabled for
  development/test use.
- The results hub store is in-memory and process-local. Multi-replica use needs
  sticky routing or a shared store before descriptors are portable across
  replicas.
- The web UI port is reserved, but the web UI is not implemented in this repo.
- Prompt-hardening behavior is implemented but default-off; enable the relevant
  flags for hardened runtime behavior.
- Historical implementation plans remain in `docs/` for traceability and may
  include commands or phase language from earlier work. Prefer this current
  state page plus the canonical specs above for new integrations.
