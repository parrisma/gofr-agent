# Copilot Instructions for gofr-agent

## GENERAL SECTION (ROOT, MACHINE)

ALL RULES ARE MANDATORY.

## A. COMMON PATTERNS, TRUTHS, AXIOMS, BEST PRACTICE

## A1. HARD RULES (MUST/NEVER)

RZ ZEROTH RULE: Be diligent and conscientious. Prefer simple, elegant solutions; never hack in changes that introduce technical debt or unnecessary complexity.
R0 SIMPLICITY: Be brief. Add complexity/verbosity ONLY when needed.
R1 CLARITY: If ambiguous -> ASK. Never guess intent or make design/product decisions.
R2 COLLAB: Treat user as partner. Show enough command output for review; do not hide critical output; do not burn context on noise.
R3 LONG_FORM: If longer than a few sentences -> write `docs/*.md`, not chat.
R4 FORMAT: Technical chat answers are plain text. Markdown is for documents only.
R5 NETWORK: Never use `localhost`. Use Docker service names on `gofr-net`. Host Docker: `host.docker.internal`.
R5a DEV CONTAINER: Running INSIDE a Docker dev container on `gofr-net`. All services (Vault, etc.) via Docker service names (e.g. `http://gofr-vault:8201`), NEVER `localhost`/`127.0.0.1`. No `docker exec` to reach services; use `curl` or CLI directly.
R6 ASCII: ASCII only in code/output. No emoji/Unicode/box drawing.
R7 GIT: Never rewrite pushed history (no `--amend`, no `rebase -i`). Use follow-up commits.
R8 PYTHON: UV only (`uv run`, `uv add`, `uv sync`). No pip/venv.
R9 LOGGING: `StructuredLogger` only. Never `print()` or stdlib `logging`.
R10 GIT OPS: Never `git add`/`commit`/`push` unless explicitly asked.

## A2. WORKFLOW (DECISION TREE)

IF change is trivial (few lines, obvious) -> implement directly.
ELSE -> Spec -> Plan -> Execute.

SPEC: `docs/<feature>_spec.md` (WHAT/WHY, constraints, assumptions, no code) -> user approval REQUIRED.
PLAN: `docs/<feature>_implementation_plan.md` (small verifiable steps, no code; update code/docs/tests; run full tests before/after) -> user approval REQUIRED.
EXECUTE: follow plan step-by-step; mark DONE; if uncovered problems appear -> STOP and discuss.

## A3. ISSUE RESOLUTION

IF bug is not an obvious one-line fix -> write `docs/<issue>_strategy.md` BEFORE code.
Strategy MUST include: symptom, hypothesised root cause, assumptions + validation, diagnostics order.
Stay on root cause. Side-issues are recorded, not chased. No root-cause claims without evidence + user validation.

## A4. PLATFORM GROUND TRUTHS

- Network: `gofr-net`. Docker service names only.
- Vault: `http://gofr-vault:8201`. Root token: `lib/gofr-common/secrets/vault_root_token`. Never `localhost` for Vault.
- Auth: shared across services. Vault path `gofr/auth`. JWT audience `gofr-api`.
- Prefer `gofr_common` helpers (auth, config, storage, logging).

## A5. TESTING

- Always use `./scripts/run_tests.sh` (env + service lifecycle). Never raw `pytest`.
- Fix code quality issues before running tests.
- Flags: `--coverage`, `-k "keyword"`, `-v`. Run targeted first, full suite after.
- Fix all failures, even seemingly unrelated ones.
- Improve `run_tests.sh` if it lacks a needed capability.

## A6. ERRORS

- Surface root cause, not side effects.
- Include: cause, context/references, recovery options.
- New domain exceptions go in `app/exceptions/`. Do not reuse generic exceptions.

## A7. MCP TOOL PATTERN

gofr-agent uses FastMCP. Every tool must:
1. Be registered as a `@mcp.tool()` decorated function in `app/mcp_server/mcp_server.py`.
2. Call `_guard(auth_service, REQUIRED_ACTIVITY)` as the first statement to enforce auth.
3. Return a plain Python value (FastMCP serialises automatically).
4. Raise `McpError(ErrorData(...))` on failure; never raise raw exceptions.
5. Have a matching activity constant in `app/auth/permissions.py`.

## A8. CODE QUALITY / HARDENING

Review all code as senior engineer + security SME:
- No secrets in code/logs; validate external inputs.
- No unbounded loops/memory; timeouts required; fail closed; least privilege.
- Maintain `tests/code_quality/test_code_quality.py` for structural checks.

## A9. PLATFORM SCRIPTS (paths relative to project root)

| Script | Purpose |
|--------|---------|
| `lib/gofr-common/scripts/auth_env.sh` | Export `VAULT_ADDR`, `VAULT_TOKEN`, `GOFR_JWT_SECRET`. Usage: `source <(./lib/gofr-common/scripts/auth_env.sh --docker)` |
| `lib/gofr-common/scripts/auth_manager.sh` | Manage auth groups/tokens (list, create, inspect, revoke). |
| `lib/gofr-common/scripts/bootstrap_auth.sh` | One-time auth bootstrap (groups + initial tokens). |
| `lib/gofr-common/scripts/bootstrap_platform.sh` | Idempotent platform bootstrap (Vault, auth, services). |
| `lib/gofr-common/scripts/manage_vault.sh` | Vault lifecycle: start, stop, status, logs, init, unseal, health. |

---

## PROJECT SECTION (gofr-agent)

PROJECT_PURPOSE: MCP Streamable-HTTP reasoning agent that orchestrates downstream MCP services via pydantic-ai.
RUNTIME: Python 3.11, UV.
ENV: VS Code dev container on Docker network `gofr-net`.
FRAMEWORK: pydantic-ai (`GofrAgent`) + FastMCP (MCP server).
LLM: OpenRouter (default model `deepseek/deepseek-v4-pro`). Provider base URL `https://openrouter.ai/api/v1`. Requires `OPENROUTER_API_KEY`.
CONFIG: all settings via `GofrAgentConfig.from_env()` with prefix `GOFR_AGENT_`. See `app/config.py`.
SESSIONS: conversation history keyed by `session_id`; stored in `SessionStore` (`app/sessions/store.py`).
SERVICES: downstream MCP services declared in `services.yml` (git-ignored; copy from `services.yml.example`). Loaded by `ServiceRegistry` (`app/services/registry.py`).
AUTH: JWT via `gofr_common` `AuthHeaderMiddleware`. Activities defined in `app/auth/permissions.py`. Dev mode: `--no-auth` flag disables auth checks.

### Port assignments

| Port | Service |
|------|---------|
| 8090 | gofr-agent MCP (Streamable HTTP) |
| 8091 | mcpo OpenAI-compatible proxy |
| 8092 | gofr-agent web UI (future) |
| 8190-8192 | Test ports (mirror of above) |

### Scripts

| Script | Purpose |
|--------|---------|
| `scripts/run_tests.sh` | THE test entry point. Run all tests (unit, integration, coverage). |
| `scripts/run-dev.sh` | Start the agent in dev mode (no auth, hot-reload). |
| `docker/compose.dev.yml` | Dev compose stack (agent + fixtures). |

### Key module map

| Module | Role |
|--------|------|
| `app/main_mcp.py` | Entry point; builds config, auth, registry, starts FastMCP server |
| `app/mcp_server/mcp_server.py` | FastMCP tool definitions (ping, list_services, ask, reset_session, register_service, refresh_services) |
| `app/agent/agent.py` | `GofrAgent` — wraps pydantic-ai `Agent`; executes reasoning loop |
| `app/agent/tool_factory.py` | Builds pydantic-ai tools from MCP service tool descriptors |
| `app/agent/system_prompt.py` | Constructs the system prompt injected into every agent run |
| `app/services/registry.py` | `ServiceRegistry` — loads manifests, manages downstream service connections |
| `app/services/pool.py` | Connection pool for downstream MCP services |
| `app/sessions/store.py` | `SessionStore` — TTL-aware conversation history |
| `app/auth/permissions.py` | Activity constants used by `_guard()` |
| `app/config.py` | `GofrAgentConfig` — all settings |

### OpenRouter integration tests

Tests in `tests/integration/test_openrouter.py` are skipped automatically when `OPENROUTER_API_KEY` is not set.
Run them with:
```
OPENROUTER_API_KEY=sk-or-... uv run python -m pytest tests/integration/test_openrouter.py -v -m openrouter
```
Default model used by tests: `deepseek/deepseek-v4-pro`.
