# gofr-agent Implementation Plan

> Each step is small enough to commit independently and includes its own tests.  
> Steps are ordered so every commit leaves the repo in a working, tested state.

---

## Testing Discipline

Every step has an explicit **verify** command. The rule is:

| Trigger | Command |
|---|---|
| After adding **any** code | `./scripts/run_tests.sh --quality` (ruff + pyright + bandit; ~5 s) |
| After completing a **step** | `./scripts/run_tests.sh --unit tests/unit/<test_file.py>` (just the new test file) |
| After completing a **phase** | `./scripts/run_tests.sh --unit` (all unit tests) |
| After Phase 10 (integration) | `./scripts/run_tests.sh` (full suite: quality → unit → integration) |
| Start of work / before commit | `./scripts/run_tests.sh --quality` |
| End of all phases | `./scripts/run_tests.sh --coverage` |

The quality gate **always runs first** regardless of which flag is used.  
If the quality gate fails, no further tests run — fix the linting/type/security issue before proceeding.

---

---

## Phase 0 — Repo Skeleton & Tooling

> **Phase checkpoint:** `./scripts/run_tests.sh --unit` must pass cleanly before moving to Phase 1.

### Step 0.1 — `pyproject.toml` and virtual environment

**Deliverables:** `pyproject.toml`, `uv.lock`, `.python-version`

- Define `[project]` with `name = "gofr-agent"`, `requires-python = ">=3.11"`.
- Add core dependencies:
  - `mcp>=1.26.0`
  - `pydantic-ai>=0.0.54`
  - `pydantic>=2.0`
  - `httpx>=0.27`
  - `pyyaml>=6.0`
  - `typer>=0.20.0`
- Add dev dependencies: `pytest>=8`, `pytest-asyncio>=0.24`, `pytest-cov`, `ruff`, `pyright`, `bandit`.
- Add `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` and `pythonpath = ["."]`.
- Add `[tool.ruff]` and `[tool.pyright]` sections matching gofr-plot standards.
- Run `uv sync` to create venv.

**Tests:** none yet — tooling only.

**Verify:** `uv run python --version` and `uv run pytest --version`.

---

### Step 0.2 — Code quality gate

**Deliverables:** `tests/__init__.py`, `tests/code_quality/__init__.py`, `tests/code_quality/test_code_quality.py`

- Copy and adapt the `TestCodeQuality` class from `gofr-plot`:
  - `test_no_linting_errors` — runs `ruff check app tests scripts`.
  - `test_no_type_errors` — runs `pyright app` only (tests and scripts are lenient; pyproject.toml controls strictness).
  - `test_no_security_issues` — runs `bandit -r app -ll -ii --skip B104` (medium+ severity, medium+ confidence; B104 skipped because binding `0.0.0.0` is intentional for a server).
- All three checks use `pytest.skip` gracefully if the tool is not installed.

**Tests:** the gate itself.

**Verify:** `uv run python -m pytest tests/code_quality/ -v`
  _(run_tests.sh does not exist yet; switch to `./scripts/run_tests.sh --quality` after Step 0.3)_

---

### Step 0.3 — `run_tests.sh`

**Deliverables:** `scripts/run_tests.sh` (executable)

- Port pattern from `gofr-plot/scripts/run_tests.sh`.
- Project-specific: `PROJECT_NAME=gofr-agent`, `ENV_PREFIX=GOFR_AGENT`, ports 8090/8091/8092.
- Default run: code quality gate first, then functional tests.
- Flags: `--unit`, `--integration`, `--coverage`, `--coverage-html`, `--stop`, `--cleanup-only`, `--docker`, `--no-servers`.
- `start_mcp_server()` launches `app/main_mcp.py --no-auth` for integration tests.
- No web or MCPO servers in v1 (add stubs that no-op).

**Tests:** quality gate only at this point — no unit tests exist yet.

**Verify:** `./scripts/run_tests.sh --quality`

---

### Step 0.4 — `app/__init__.py` and `app/exceptions/`

**Deliverables:** `app/__init__.py`, `app/exceptions/__init__.py`, `app/exceptions/errors.py`

- Define exception hierarchy:
  - `GofrAgentError(Exception)` — base.
  - `ServiceConnectionError(GofrAgentError)` — pool/connection failures.
  - `ToolDiscoveryError(GofrAgentError)` — failed tool list.
  - `SessionNotFoundError(GofrAgentError)` — bad `session_id`.
  - `ToolResultTruncatedError(GofrAgentError)` — informational, not raised to caller.
  - `ConfigurationError(GofrAgentError)` — invalid startup config.

**Tests:** `tests/unit/test_exceptions.py` — instantiate each, check message and hierarchy.

**Verify:** `./scripts/run_tests.sh --quality && ./scripts/run_tests.sh --unit tests/unit/test_exceptions.py`

---

### Step 0.5 — Port registration in `gofr-common`

**Deliverables:** edits to `lib/gofr-common/config/gofr_ports.env` and `lib/gofr-common/src/gofr_common/config/ports.py`

- Add to `gofr_ports.env`:
  ```
  GOFR_AGENT_MCP_PORT=8090
  GOFR_AGENT_MCPO_PORT=8091
  GOFR_AGENT_WEB_PORT=8092
  GOFR_AGENT_MCP_PORT_TEST=8190
  GOFR_AGENT_MCPO_PORT_TEST=8191
  GOFR_AGENT_WEB_PORT_TEST=8192
  ```
- Add `'gofr-agent': ServicePorts(mcp=8090, mcpo=8091, web=8092)` to `_DEFAULT_PORTS`.
- Export `GOFR_AGENT_PORTS` from `__init__.py`.

**Tests:** `tests/unit/test_config.py` — assert `GOFR_AGENT_PORTS.mcp == 8090`, `.mcpo == 8091`, `.web == 8092`.

**Verify:** `./scripts/run_tests.sh --quality && ./scripts/run_tests.sh --unit tests/unit/test_config.py`

> **Phase 0 checkpoint:** `./scripts/run_tests.sh --unit`

---

## Phase 1 — Configuration Layer

> **Phase checkpoint:** `./scripts/run_tests.sh --unit` must pass cleanly before moving to Phase 2.

### Step 1.1 — `app/logger/`

**Deliverables:** `app/logger/__init__.py`

- Thin re-export of `gofr_common.logger.ConsoleLogger`.
- No logic, just the import alias used throughout the project.

**Tests:** `tests/unit/test_logger.py` — import succeeds, can instantiate `ConsoleLogger`.

**Verify:** `./scripts/run_tests.sh --quality && ./scripts/run_tests.sh --unit tests/unit/test_logger.py`

---

### Step 1.2 — `app/config.py`

**Deliverables:** `app/config.py`

- Define `GofrAgentConfig` as a `pydantic.BaseModel` (not `BaseSettings` — loaded explicitly).
- Fields (all with defaults or optional):

  | Field | Type | Default |
  |---|---|---|
  | `mcp_port` | int | 8090 |
  | `mcpo_port` | int | 8091 |
  | `host` | str | `"0.0.0.0"` |
  | `llm_model` | str | `"openai:gpt-4o-mini"` |
  | `jwt_secret` | str \| None | None |
  | `require_auth` | bool | True |
  | `services_file` | Path \| None | None |
  | `max_steps` | int | 10 |
  | `session_ttl_minutes` | int | 60 |
  | `tool_result_max_chars` | int | 4000 |
  | `session_pool_size` | int | 3 |
  | `log_level` | str | `"INFO"` |

- Validator: if `require_auth` is True and `jwt_secret` is None → raise `ConfigurationError`.
- `@classmethod from_env(prefix="GOFR_AGENT") -> GofrAgentConfig` — reads env vars.

**Tests:** `tests/unit/test_config.py`
- `from_env` with all env vars set produces correct values.
- `from_env` with missing `jwt_secret` and `require_auth=True` raises `ConfigurationError`.
- `from_env` with `require_auth=False` succeeds with no secret.
- Defaults are correct when no env vars set.

**Verify:** `./scripts/run_tests.sh --quality && ./scripts/run_tests.sh --unit tests/unit/test_config.py`

---

### Step 1.3 — `app/settings.py`

**Deliverables:** `app/settings.py`

- Re-export `gofr_common.config.Settings` with `GOFR_AGENT` prefix, same pattern as `gofr-plot/app/settings.py`.
- Expose `get_settings()` convenience function.

**Tests:** `tests/unit/test_settings.py` — `get_settings(require_auth=False)` returns a `Settings` instance.

**Verify:** `./scripts/run_tests.sh --quality && ./scripts/run_tests.sh --unit tests/unit/test_settings.py`

> **Phase 1 checkpoint:** `./scripts/run_tests.sh --unit`

---

## Phase 2 — Service Models & Configuration Loading

> **Phase checkpoint:** `./scripts/run_tests.sh --unit` must pass cleanly before moving to Phase 3.

### Step 2.1 — `app/services/models.py`

**Deliverables:** `app/services/models.py`

- `ServiceConfig(BaseModel)`:
  - `name: str`
  - `url: str` (validated as HTTP URL)
  - `token: str | None = None`
  - `token_env: str | None = None` — if set, token is read from this env var at load time
  - `description: str = ""`
  - `enabled: bool = True`
  - `timeout_s: float = 30.0`
  - `pool_size: int | None = None` — overrides global `session_pool_size` if set
  - `@model_validator(mode="after")` resolves `token_env` → `token`

- `ServicesManifest(BaseModel)`:
  - `services: list[ServiceConfig]`
  - `@classmethod from_yaml(path: Path) -> ServicesManifest`
  - `@classmethod from_env(prefix: str = "GOFR_AGENT") -> ServicesManifest`
    - reads `GOFR_AGENT_SERVICES=plot,iq`, then `GOFR_AGENT_PLOT_URL`, `GOFR_AGENT_PLOT_TOKEN` etc.

**Tests:** `tests/unit/test_service_models.py`
- Valid YAML round-trips through `from_yaml`.
- `token_env` resolution picks up env var value.
- Missing required `url` raises `ValidationError`.
- `from_env` with `GOFR_AGENT_SERVICES=plot` and `GOFR_AGENT_PLOT_URL=http://x/mcp` produces one `ServiceConfig`.
- Disabled services survive parsing.

**Verify:** `./scripts/run_tests.sh --quality && ./scripts/run_tests.sh --unit tests/unit/test_service_models.py`

> **Phase 2 checkpoint:** `./scripts/run_tests.sh --unit`

---

## Phase 3 — Session Pool

> **Phase checkpoint:** `./scripts/run_tests.sh --unit` must pass cleanly before moving to Phase 4.

### Step 3.1 — `app/services/pool.py`

**Deliverables:** `app/services/pool.py`

- `class SessionPool`:
  - `__init__(self, service: ServiceConfig, pool_size: int)`
  - Holds `_slots: list[ClientSession | None]` of length `pool_size`.
  - `_semaphore: asyncio.Semaphore(pool_size)`.
  - `_lock: asyncio.Lock` for slot list mutations.
  - `async def start() -> None` — opens all slots (calls `_open_slot` for each index).
  - `async def stop() -> None` — closes all slots.
  - `@asynccontextmanager async def checkout() -> AsyncIterator[ClientSession]` — acquires semaphore, finds a live slot, yields it, returns it.
  - `async def _open_slot(index: int) -> None` — creates `streamablehttp_client` context manager, stores session in slot.
  - `async def _reconnect_loop(index: int) -> None` — background task: on slot disconnect, waits with exponential back-off (1s, 2s, 4s, … max 60s), retries `_open_slot`.
  - `property is_healthy: bool` — True if at least one slot is live.

**Tests:** `tests/unit/test_pool.py` — use `unittest.mock.AsyncMock` / `pytest-mock` to mock the MCP client:
- `start()` opens `pool_size` connections.
- `checkout()` as context manager yields a session and returns it.
- Concurrent `checkout()` calls up to `pool_size` all succeed immediately.
- `pool_size + 1` concurrent calls: last one waits (use `asyncio.gather` with a small timeout assertion).
- `stop()` closes all slots.
- Reconnect loop called when slot is None (simulated disconnect).

**Verify:** `./scripts/run_tests.sh --quality && ./scripts/run_tests.sh --unit tests/unit/test_pool.py`

> **Phase 3 checkpoint:** `./scripts/run_tests.sh --unit`

---

## Phase 4 — Tool Discovery

> **Phase checkpoint:** `./scripts/run_tests.sh --unit` must pass cleanly before moving to Phase 5.

### Step 4.1 — `app/services/discovery.py`

**Deliverables:** `app/services/discovery.py`

- `async def discover_tools(pool: SessionPool, service: ServiceConfig) -> list[MCPToolInfo]`
  - Checks out one session, calls `session.list_tools()`, returns raw tool list.
  - Raises `ToolDiscoveryError` on failure.
- `MCPToolInfo` dataclass: `name`, `description`, `input_schema` (dict), `service_name`.

**Tests:** `tests/unit/test_discovery.py`
- Mock `session.list_tools()` returning two tools → returns two `MCPToolInfo` objects.
- Mock raising an exception → `ToolDiscoveryError` is raised.
- `service_name` is populated from `service.name`.

**Verify:** `./scripts/run_tests.sh --quality && ./scripts/run_tests.sh --unit tests/unit/test_discovery.py`

---

### Step 4.2 — `app/agent/tool_factory.py`

**Deliverables:** `app/agent/tool_factory.py`

- `def make_tool(pool: SessionPool, info: MCPToolInfo, max_chars: int) -> Tool`
  - Builds a pydantic-ai `Tool` whose async `call` function:
    1. Checks out a session from `pool`.
    2. Calls `session.call_tool(info.name, kwargs)`.
    3. Extracts text content, truncates to `max_chars` preserving any URL.
    4. Returns the (possibly truncated) string.
  - Tool name: `f"{info.service_name}__{info.name}"`.
  - Tool description: `info.description`.
- `def truncate_result(text: str, max_chars: int) -> str`
  - If `len(text) <= max_chars` → return as-is.
  - Extract first URL from text (regex `https?://\S+`).
  - Return `text[:max_chars] + f"\n[... truncated. URL: {url}]"` if URL found, else `text[:max_chars] + "\n[... truncated]"`.

**Tests:** `tests/unit/test_tool_factory.py`
- `truncate_result` with short text → unchanged.
- `truncate_result` with long text → truncated with notice.
- `truncate_result` with long text containing URL → URL preserved in notice.
- `make_tool` returns a `Tool` with correct name `svc__toolname`.
- `make_tool` call function invokes `pool.checkout()` and `session.call_tool()`.
- `make_tool` call function truncates result when over limit.

**Verify:** `./scripts/run_tests.sh --quality && ./scripts/run_tests.sh --unit tests/unit/test_tool_factory.py`

> **Phase 4 checkpoint:** `./scripts/run_tests.sh --unit`

---

## Phase 5 — Service Registry

> **Phase checkpoint:** `./scripts/run_tests.sh --unit` must pass cleanly before moving to Phase 6.

### Step 5.1 — `app/services/registry.py`

**Deliverables:** `app/services/registry.py`

- `class ServiceRegistry`:
  - `__init__(self, config: GofrAgentConfig)`
  - `_services: dict[str, ServiceConfig]`
  - `_pools: dict[str, SessionPool]`
  - `_tools: dict[str, list[MCPToolInfo]]` — per service, discovered tools
  - `async def load_manifest(manifest: ServicesManifest) -> None`
    - For each enabled service: creates pool, calls `pool.start()`, calls `discover_tools()`.
    - Failed services log a warning and are skipped (partial degradation).
  - `async def register_service(config: ServiceConfig) -> list[MCPToolInfo]`
    - Creates pool, starts it, discovers tools, stores all, returns tool list.
    - Thread-safe via internal `asyncio.Lock`.
  - `async def shutdown() -> None` — stops all pools.
  - `@property all_tools: list[MCPToolInfo]` — flat list across all services.
  - `@property all_pools: dict[str, SessionPool]`
  - `def get_pool(name: str) -> SessionPool | None`

**Tests:** `tests/unit/test_registry.py`
- `load_manifest` with two services: both pools started, both tool lists populated.
- One unreachable service: warning logged, other service still registered, no exception.
- `register_service` adds to existing registry.
- `all_tools` returns union of all service tools.
- `shutdown` calls `stop()` on all pools.

**Verify:** `./scripts/run_tests.sh --quality && ./scripts/run_tests.sh --unit tests/unit/test_registry.py`

> **Phase 5 checkpoint:** `./scripts/run_tests.sh --unit`

---

## Phase 6 — Session Store

> **Phase checkpoint:** `./scripts/run_tests.sh --unit` must pass cleanly before moving to Phase 7.

### Step 6.1 — `app/sessions/store.py`

**Deliverables:** `app/sessions/store.py`

- `@dataclass class Session`:
  - `session_id: str`
  - `messages: list` (pydantic-ai `ModelMessage` list, typed as `list[Any]` initially)
  - `lock: asyncio.Lock`
  - `created_at: datetime`
  - `last_active: datetime`

- `class SessionStore`:
  - `_sessions: dict[str, Session]`
  - `_lock: asyncio.Lock` (guards dict mutations)
  - `_ttl_minutes: int`
  - `async def get_or_create(session_id: str | None) -> Session`
    - If `None` or unknown: creates new session with `uuid4()` ID.
    - Updates `last_active`.
  - `async def clear(session_id: str) -> None` — empties messages, keeps session.
  - `async def delete(session_id: str) -> None` — removes session entirely.
  - `async def sweep_expired(self) -> int` — removes sessions idle > TTL, returns count removed.
  - `async def start_ttl_sweep(self) -> None` — background task calling `sweep_expired` every 60s.

**Tests:** `tests/unit/test_session_store.py`
- `get_or_create(None)` → new session with generated ID.
- `get_or_create(existing_id)` → same session object.
- `get_or_create(unknown_id)` → new session (not the given ID).
- `clear(id)` empties messages, session still exists.
- `sweep_expired` removes sessions past TTL, leaves recent ones.
- Concurrent `get_or_create` calls with same ID return same session (no duplicates).

**Verify:** `./scripts/run_tests.sh --quality && ./scripts/run_tests.sh --unit tests/unit/test_session_store.py`

> **Phase 6 checkpoint:** `./scripts/run_tests.sh --unit`

---

## Phase 7 — Agent

> **Phase checkpoint:** `./scripts/run_tests.sh --unit` must pass cleanly before moving to Phase 8.

### Step 7.1 — `app/agent/system_prompt.py`

**Deliverables:** `app/agent/system_prompt.py`

- `def build_system_prompt(services: list[ServiceConfig], tool_infos: list[MCPToolInfo]) -> str`
  - Preamble: role description ("You are a reasoning agent with access to the following tools…").
  - Per-service block: service name, description, indented list of `svc__tool` names with descriptions.
  - Footer: instructions on when to call tools vs. answer directly.

**Tests:** `tests/unit/test_system_prompt.py`
- With zero services → prompt still valid, contains preamble.
- With two services → both names appear, all tool names appear.
- Tool names use `__` namespace separator.

**Verify:** `./scripts/run_tests.sh --quality && ./scripts/run_tests.sh --unit tests/unit/test_system_prompt.py`

---

### Step 7.2 — `app/agent/agent.py`

**Deliverables:** `app/agent/agent.py`

- `class GofrAgent`:
  - `__init__(self, config: GofrAgentConfig, registry: ServiceRegistry)`
  - `_agent: pydantic_ai.Agent | None = None`
  - `def build(self) -> None` — constructs `pydantic_ai.Agent` from `registry.all_tools` and `build_system_prompt`.
  - `def rebuild(self) -> None` — called after `register_service`; replaces `_agent`.
  - `async def run(self, question: str, session: Session, context: str | None, max_steps: int, on_step: Callable[[dict], Awaitable[None]]) -> AgentResult`
    - Acquires `session.lock` to read `session.messages`.
    - Calls `self._agent.run_stream(question, message_history=messages, model_settings={"max_steps": max_steps})`.
    - For each streaming event: if it's a tool call or result, calls `on_step(step_dict)`.
    - Acquires `session.lock` to append new messages to `session.messages`.
    - Returns `AgentResult(answer=str, steps=list[dict], model=str, tokens_used=int)`.
  - Lock is released between read and write (not held across LLM call).

- `@dataclass class AgentResult`:
  - `answer: str`
  - `steps: list[dict]`
  - `model: str`
  - `tokens_used: int`

**Tests:** `tests/unit/test_agent.py`
- `build()` with mock registry creates an `Agent`.
- `rebuild()` replaces the agent instance.
- `run()` with mocked `pydantic_ai.Agent.run_stream` calls `on_step` for each tool event.
- `run()` appends to `session.messages` after completion.
- Concurrent `run()` on different sessions: both complete (no lock contention).
- Concurrent `run()` on same session: second waits for lock on history (messages not corrupted).

**Verify:** `./scripts/run_tests.sh --quality && ./scripts/run_tests.sh --unit tests/unit/test_agent.py`

> **Phase 7 checkpoint:** `./scripts/run_tests.sh --unit`

---

## Phase 8 — MCP Server

> **Phase checkpoint:** `./scripts/run_tests.sh --unit` must pass cleanly before moving to Phase 9.

### Step 8.1 — `app/mcp_server/mcp_server.py`

**Deliverables:** `app/mcp_server/__init__.py`, `app/mcp_server/mcp_server.py`

- Use `mcp.server.fastmcp.FastMCP` (same as gofr-iq).
- Module-level singletons: `registry: ServiceRegistry`, `agent: GofrAgent`, `session_store: SessionStore`.
- `def create_mcp_server(config: GofrAgentConfig, ...) -> FastMCP` — injectable for testing.
- Tools:

  **`ping`** → `{"status": "ok", "timestamp": "...", "version": "0.1.0"}`

  **`list_services`** → list of `{name, url, status, tools: [{name, description}]}`

  **`ask(question, session_id?, context?, max_steps?, model_override?)`**
    - Gets/creates session.
    - Calls `agent.run(...)` with `on_step` that emits MCP notifications via `ctx.session.send_log_message(...)`.
    - Returns JSON of `AgentResult` + `session_id`.

  **`reset_session(session_id)`** → calls `session_store.clear(session_id)`.

  **`register_service(name, url, token?, description?)`**
    - Builds `ServiceConfig`, calls `registry.register_service()`, calls `agent.rebuild()`.
    - Returns `{status, name, tools_discovered}`.

  **`refresh_services`** (admin) → re-discovers all services, calls `agent.rebuild()`.

**Tests:** `tests/unit/test_mcp_server.py`
- Mock `registry` and `agent`; call each tool handler directly (not via HTTP).
- `ping` returns expected shape.
- `list_services` returns service list from registry.
- `ask` calls `agent.run()` and returns `session_id`.
- `ask` with existing `session_id` reuses session.
- `reset_session` calls `session_store.clear()`.
- `register_service` calls `registry.register_service()` and `agent.rebuild()`.

**Verify:** `./scripts/run_tests.sh --quality && ./scripts/run_tests.sh --unit tests/unit/test_mcp_server.py`

---

### Step 8.2 — `app/auth/`

**Deliverables:** `app/auth/__init__.py`

- Thin re-export of `gofr_common.auth.AuthService`.
- No custom logic; auth middleware is applied at the ASGI layer from gofr-common.

**Tests:** `tests/unit/test_auth.py` — import succeeds; `AuthService` is the gofr-common class.

**Verify:** `./scripts/run_tests.sh --quality && ./scripts/run_tests.sh --unit tests/unit/test_auth.py`

> **Phase 8 checkpoint:** `./scripts/run_tests.sh --unit`

---

## Phase 9 — Entry Points

> **Phase checkpoint:** `./scripts/run_tests.sh --unit` must pass cleanly before moving to Phase 10.

### Step 9.1 — `app/main_mcp.py`

**Deliverables:** `app/main_mcp.py`

- CLI via `argparse` (same pattern as gofr-plot).
- Arguments: `--host`, `--port`, `--jwt-secret`, `--no-auth`, `--services-file`, `--log-level`, `--pool-size`.
- Startup sequence (see SPEC §13):
  1. Build `GofrAgentConfig` from args + env.
  2. Load `ServicesManifest`.
  3. Create and start `ServiceRegistry`.
  4. Build `GofrAgent`.
  5. Create `SessionStore`, start TTL sweep task.
  6. Call `create_mcp_server(config, registry, agent, session_store)`.
  7. Run with uvicorn.
- Graceful shutdown via `asyncio` signal handlers: stop registry, cancel sweep task.

**Tests:** none for the entrypoint itself (covered by integration tests).

**Verify:** `./scripts/run_tests.sh --quality && uv run python app/main_mcp.py --help`

---

### Step 9.2 — `app/cli/ask.py`

**Deliverables:** `app/cli/__init__.py`, `app/cli/ask.py`

- `typer` CLI: `ask [QUESTION] [--session SESSION_ID] [--reset SESSION_ID] [--url URL] [--no-auth]`.
- Connects to gofr-agent MCP via `mcp.client.streamable_http.streamablehttp_client`.
- Calls `ask` tool, listens for `notifications/message` events, prints each step as it arrives.
- Final answer rendered after all steps.
- `--reset` calls `reset_session` tool then exits.

**Tests:** `tests/unit/test_cli.py`
- `typer.testing.CliRunner` invokes the CLI with a mocked MCP client.
- Step notifications are printed before the final answer.
- `--reset` sends `reset_session` call.

**Verify:** `./scripts/run_tests.sh --quality && ./scripts/run_tests.sh --unit tests/unit/test_cli.py`

> **Phase 9 checkpoint:** `./scripts/run_tests.sh --unit`

---

## Phase 10 — Integration Tests

> This phase adds integration tests only — no new `app/` code.  
> **Phase checkpoint (end):** `./scripts/run_tests.sh` — **full suite** (quality → unit → integration).

### Step 10.1 — Mock downstream MCP server fixture

**Deliverables:** `tests/integration/conftest.py`, `tests/integration/mock_mcp_server.py`, `tests/integration/test_mock_mcp_server.py`

- An in-process FastMCP server with two stub tools:
  - `echo(text: str) -> str` — returns the input.
  - `add(a: int, b: int) -> int` — returns `a + b`.
- Pytest fixture `mock_mcp_server` that starts the server on a random port and yields its URL.
- Fixture `mock_manifest_file(tmp_path, mock_mcp_server)` — writes a `services.yml` pointing to the mock.

**Tests:** `tests/integration/test_mock_mcp_server.py` — `echo` returns input, `add` returns sum.
  _(Pytest does not collect test functions from `conftest.py`; the fixture self-test lives in this dedicated module.)_

**Verify:** `./scripts/run_tests.sh --quality && ./scripts/run_tests.sh --integration tests/integration/test_mock_mcp_server.py`

---

### Step 10.2 — Registry integration test

**Deliverables:** `tests/integration/test_registry_integration.py`

- Uses `mock_mcp_server` fixture.
- `test_discover_tools_live` — start registry with mock manifest, assert two tools discovered.
- `test_pool_checkout_live` — checkout session, call `echo`, get result.
- `test_concurrent_pool_checkouts` — 10 concurrent `echo` calls with `pool_size=3`; all succeed.
- `test_service_unreachable_at_startup` — bad URL in manifest; registry starts with warning, no exception.

**Verify:** `./scripts/run_tests.sh --quality && ./scripts/run_tests.sh --integration tests/integration/test_registry_integration.py`

---

### Step 10.3 — Agent integration test

**Deliverables:** `tests/integration/test_agent_integration.py`

- Uses `mock_mcp_server` fixture and a mock LLM (pydantic-ai `TestModel` or equivalent).
- `test_ask_calls_echo_tool` — question triggers the agent to call `echo`; result in answer.
- `test_ask_session_continuity` — two sequential asks on same session; second ask has prior context in messages.
- `test_ask_reset_session` — clear session; subsequent ask starts fresh.
- `test_ask_concurrent_different_sessions` — 5 concurrent asks on distinct sessions complete without error.
- `test_ask_concurrent_same_session` — 2 concurrent asks on same session complete; messages not corrupted.

**Verify:** `./scripts/run_tests.sh --quality && ./scripts/run_tests.sh --integration tests/integration/test_agent_integration.py`

---

### Step 10.4 — MCP server integration test

**Deliverables:** `tests/integration/test_mcp_server_integration.py`

- Starts the full gofr-agent MCP server via `create_mcp_server(config)` in-process (no subprocess).
- Uses httpx async client to hit `POST /mcp`.
- `test_ping_tool` — call `ping`, get expected shape.
- `test_list_services_tool` — call `list_services`, mock service appears.
- `test_ask_tool_e2e` — call `ask`, verify `session_id` returned, answer non-empty.
- `test_register_service_tool` — register a new service at runtime; `list_services` shows it.
- `test_auth_required` — with auth enabled and no token, get auth error.

**Verify:** `./scripts/run_tests.sh --quality && ./scripts/run_tests.sh --integration tests/integration/test_mcp_server_integration.py`

> **Phase 10 checkpoint — full suite:** `./scripts/run_tests.sh`

---

## Phase 11 — `services.yml.example` and README

> **Final checkpoint:** `./scripts/run_tests.sh --coverage`

### Step 11.1 — Example files and README

**Deliverables:** `services.yml.example`, `README.md`

- `services.yml.example` shows all fields with comments.
- `README.md` covers: purpose, quickstart (`uv run python app/main_mcp.py --no-auth --services-file services.yml`), CLI usage, config reference (table from SPEC §10), and a note about running `./scripts/run_tests.sh`.

**Tests:** none for docs. Quality gate checks `scripts/` for linting (Python helper scripts only).

**Verify:** `./scripts/run_tests.sh --coverage`

---

## Step Ordering Summary

`Q` = `--quality` only &nbsp;|&nbsp; `U:<file>` = `--unit <file>` &nbsp;|&nbsp; `U` = `--unit` (all) &nbsp;|&nbsp; `I:<file>` = `--integration <file>` &nbsp;|&nbsp; `FULL` = full suite &nbsp;|&nbsp; ¹ = direct pytest (runner not yet created)

| Step | Deliverable | Depends on | Verify after step |
|---|---|---|---|
| 0.1 | pyproject.toml, venv | — | `Q` |
| 0.2 | Code quality gate | 0.1 | `uv run pytest tests/code_quality/ -v` ¹ |
| 0.3 | run_tests.sh | 0.2 | `Q` |
| 0.4 | exceptions | 0.1 | `Q` + `U:test_exceptions.py` |
| 0.5 | Port registration (gofr-common) | 0.1 | `Q` + `U:test_config.py` |
| — | **Phase 0 checkpoint** | — | **`U`** |
| 1.1 | logger re-export | 0.1 | `Q` + `U:test_logger.py` |
| 1.2 | GofrAgentConfig | 0.4 | `Q` + `U:test_config.py` |
| 1.3 | settings.py | 1.2 | `Q` + `U:test_settings.py` |
| — | **Phase 1 checkpoint** | — | **`U`** |
| 2.1 | ServiceConfig / ServicesManifest | 1.2 | `Q` + `U:test_service_models.py` |
| — | **Phase 2 checkpoint** | — | **`U`** |
| 3.1 | SessionPool | 2.1 | `Q` + `U:test_pool.py` |
| — | **Phase 3 checkpoint** | — | **`U`** |
| 4.1 | discover_tools | 3.1 | `Q` + `U:test_discovery.py` |
| 4.2 | tool_factory | 4.1 | `Q` + `U:test_tool_factory.py` |
| — | **Phase 4 checkpoint** | — | **`U`** |
| 5.1 | ServiceRegistry | 3.1, 4.1 | `Q` + `U:test_registry.py` |
| — | **Phase 5 checkpoint** | — | **`U`** |
| 6.1 | SessionStore | 0.4 | `Q` + `U:test_session_store.py` |
| — | **Phase 6 checkpoint** | — | **`U`** |
| 7.1 | system_prompt | 2.1, 4.1 | `Q` + `U:test_system_prompt.py` |
| 7.2 | GofrAgent | 7.1, 4.2, 6.1 | `Q` + `U:test_agent.py` |
| — | **Phase 7 checkpoint** | — | **`U`** |
| 8.1 | MCP server tools | 7.2, 5.1 | `Q` + `U:test_mcp_server.py` |
| 8.2 | auth re-export | 0.1 | `Q` + `U:test_auth.py` |
| — | **Phase 8 checkpoint** | — | **`U`** |
| 9.1 | main_mcp.py | 8.1, 8.2 | `Q` + `--help` smoke |
| 9.2 | CLI ask.py | 8.1 | `Q` + `U:test_cli.py` |
| — | **Phase 9 checkpoint** | — | **`U`** |
| 10.1 | mock MCP fixture | 9.1 | `Q` + `I:test_mock_mcp_server.py` |
| 10.2 | Registry integration | 10.1 | `Q` + `I:test_registry_integration.py` |
| 10.3 | Agent integration | 10.1, 7.2 | `Q` + `I:test_agent_integration.py` |
| 10.4 | MCP server integration | 9.1, 10.1 | `Q` + `I:test_mcp_server_integration.py` |
| — | **Phase 10 checkpoint** | — | **`FULL`** |
| 11.1 | README + example | all | **`FULL --coverage`** |

---

## Test File Map

```
tests/
├── __init__.py
├── code_quality/
│   ├── __init__.py
│   └── test_code_quality.py      # ruff + pyright + bandit gate (step 0.2)
├── unit/
│   ├── __init__.py
│   ├── test_exceptions.py        # step 0.4
│   ├── test_config.py            # steps 0.5, 1.2
│   ├── test_settings.py          # step 1.3
│   ├── test_logger.py            # step 1.1
│   ├── test_service_models.py    # step 2.1
│   ├── test_pool.py              # step 3.1
│   ├── test_discovery.py         # step 4.1
│   ├── test_tool_factory.py      # step 4.2
│   ├── test_registry.py          # step 5.1
│   ├── test_session_store.py     # step 6.1
│   ├── test_system_prompt.py     # step 7.1
│   ├── test_agent.py             # step 7.2
│   ├── test_mcp_server.py        # step 8.1
│   ├── test_auth.py              # step 8.2
│   └── test_cli.py               # step 9.2
└── integration/
    ├── __init__.py
    ├── conftest.py               # mock MCP server fixture (step 10.1)
    ├── mock_mcp_server.py        # stub FastMCP server (step 10.1)
    ├── test_mock_mcp_server.py   # fixture self-test (step 10.1)
    ├── test_registry_integration.py   # step 10.2
    ├── test_agent_integration.py      # step 10.3
    └── test_mcp_server_integration.py # step 10.4
```
