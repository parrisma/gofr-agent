# gofr-agent Auth Implementation Plan

> Implements the design described in `docs/auth_mini_spec.md`.  
> Each step is small enough to commit independently and leaves all tests green.  
> Start with 131 passing tests. End with ≥ 131 + new auth tests.

---

## Testing Discipline

Same rules as the main `IMPL_PLAN.md`:

| Trigger | Command |
|---|---|
| After **any** code change | `uv run ruff check app tests scripts` |
| After completing a **step** | `uv run python -m pytest <new test file> -v` |
| After completing a **phase** | `uv run python -m pytest tests/unit/ -q` |
| After Phase E (integration) | `uv run python -m pytest tests/ -q` |
| Before moving on | full suite must be green |

---

## Dependency Map

```
Phase A  ──► Phase B0 ──► Phase B  ──► Phase C  ──► Phase D
                           │                          │
                           └──────────► Phase E ◄─────┘
```

Each phase depends only on the one before it.  
Phases A–D can be reviewed in isolation.  Phase E wires them together.

**Important guardrail:** default runtime auth must fail closed. Development can use
fixed dev tokens, but there must not be a normal runtime path where any non-empty
token receives administrator access.

---

## Phase A — Auth Primitives

> **Goal:** Create the stable auth interface, error types, activity helpers, and token extractor.  
> **Phase checkpoint:** `uv run python -m pytest tests/unit/test_auth_*.py -v` all green.

---

### Step A.1 — Error types in `app/exceptions/errors.py`

**Why first:** All other auth modules import these; no circular deps.

**Deliverables:** add three classes to `app/exceptions/errors.py`

```python
class AuthorizationError(GofrAgentError):
    """Raised when a token lacks the required activity."""
    def __init__(self, required_activity: str) -> None:
        super().__init__(f"Not authorized for activity: {required_activity}")
        self.required_activity = required_activity


class AuthServiceError(GofrAgentError):
    """Base for auth service failures."""


class AuthTokenInvalidError(AuthServiceError):
    """Token is missing, malformed, or rejected."""


class AuthServiceUnavailableError(AuthServiceError):
    """The auth backend cannot answer authorization questions."""
```

Re-export all four from `app/exceptions/__init__.py`.

**Tests:** `tests/unit/test_auth_errors.py`

```python
from app.exceptions import (
    AuthorizationError,
    AuthServiceError,
    AuthTokenInvalidError,
    AuthServiceUnavailableError,
)

def test_authorization_error_message():
    err = AuthorizationError("GoFRAgentAsk")
    assert "GoFRAgentAsk" in str(err)
    assert err.required_activity == "GoFRAgentAsk"

def test_auth_error_hierarchy():
    assert issubclass(AuthTokenInvalidError, AuthServiceError)
    assert issubclass(AuthServiceUnavailableError, AuthServiceError)
    assert issubclass(AuthServiceError, Exception)
```

**Verify:** `uv run python -m pytest tests/unit/test_auth_errors.py -v`

---

### Step A.2 — `AuthService` Protocol in `app/auth/auth_service.py`

**Why:** Stable interface everything else depends on.

**Deliverables:** Replace contents of `app/auth/auth_service.py` (new file — current `app/auth/` only has `__init__.py`).

```python
"""AuthService protocol and factory."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AuthService(Protocol):
    def authorised_activities(self, token: str) -> str:
        """Return authorized activities as a comma-separated string.

        Returns an empty string for unknown or unauthorised tokens.
        Raises AuthServiceUnavailableError if the backend cannot respond.
        """
        ...


def get_auth_service() -> AuthService:
    """Return the configured auth service for production use.

    The default factory fails closed. Tests inject DummyAuthService directly.
    Development may opt into a fixed-token implementation only via an explicit
    GOFR_AGENT_AUTH_MODE=dev setting.
    """
    import os

    if os.environ.get("GOFR_AGENT_AUTH_MODE") == "dev":
        from app.auth._dev_auth_service import DevAuthService  # noqa: PLC0415

        return DevAuthService()
    return FailClosedAuthService()


class FailClosedAuthService:
    """Default AuthService implementation: deny every token."""

    def authorised_activities(self, token: str) -> str:
        return ""
```

**Tests:** `tests/unit/test_auth_service_protocol.py`

```python
from typing import runtime_checkable
from app.auth.auth_service import AuthService

class _Fake:
    def authorised_activities(self, token: str) -> str:
        return ""

def test_fake_satisfies_protocol():
    assert isinstance(_Fake(), AuthService)

def test_missing_method_does_not_satisfy_protocol():
    class _Bad:
        pass
    assert not isinstance(_Bad(), AuthService)
```

**Verify:** `uv run python -m pytest tests/unit/test_auth_service_protocol.py -v`

---

### Step A.3 — `DevAuthService` in `app/auth/_dev_auth_service.py`

**Why:** Local development needs a predictable implementation without disabling auth.  
Kept in `app/auth/` with a leading underscore to signal "internal / not part of public API."  
Tests use `DummyAuthService` from `tests/helpers/` instead.

**Deliverables:** `app/auth/_dev_auth_service.py`

```python
"""Development-only auth service.

Accepts only fixed development tokens.
NOT for production use — enabled only with GOFR_AGENT_AUTH_MODE=dev.
"""
from __future__ import annotations

from app.auth.permissions import (
    AGENT_ASK,
    AGENT_LIST_SERVICES,
    AGENT_PING,
    AGENT_REFRESH_SERVICES,
    AGENT_REGISTER_SERVICE,
    AGENT_RESET_SESSION,
)

_ADMIN_ACTIVITIES = ",".join([
    AGENT_PING,
    AGENT_LIST_SERVICES,
    AGENT_ASK,
    AGENT_RESET_SESSION,
    AGENT_REGISTER_SERVICE,
    AGENT_REFRESH_SERVICES,
    "MCPServerRagToolSearch",
    "MCPServerDocsDataRead",
    "MCPServerSandboxExecute",
])

_READ_ACTIVITIES = ",".join([
    AGENT_PING,
    AGENT_LIST_SERVICES,
    AGENT_ASK,
])

_TOKEN_MAP = {
    "dev-admin-token": _ADMIN_ACTIVITIES,
    "dev-read-token": _READ_ACTIVITIES,
}


class DevAuthService:
    """Fixed-token development implementation."""

    def authorised_activities(self, token: str) -> str:
        return _TOKEN_MAP.get(token, "")
```

**Tests:** covered implicitly by Step A.5 via `get_auth_service()`.  
Minimal smoke test in `test_auth_service_protocol.py`:

```python
from app.auth.auth_service import get_auth_service
from app.auth.auth_service import AuthService

def test_get_auth_service_returns_auth_service():
    svc = get_auth_service()
    assert isinstance(svc, AuthService)
    # default impl fails closed
    result = svc.authorised_activities("any-token")
    assert result == ""

def test_get_auth_service_dev_mode(monkeypatch):
    monkeypatch.setenv("GOFR_AGENT_AUTH_MODE", "dev")
    svc = get_auth_service()
    assert "GoFRAgentAsk" in svc.authorised_activities("dev-admin-token")
    assert svc.authorised_activities("any-token") == ""
```

**Verify:** `uv run python -m pytest tests/unit/test_auth_service_protocol.py -v`

---

### Step A.4 — Activity constants in `app/auth/permissions.py`

**Why:** Centralises all activity strings so there is one source of truth.

**Deliverables:** `app/auth/permissions.py`

```python
"""Activity strings and authorization helpers."""
from __future__ import annotations

from app.exceptions import AuthorizationError

# ── gofr-agent operations ────────────────────────────────────────────
AGENT_PING             = "GoFRAgentPing"
AGENT_LIST_SERVICES    = "GoFRAgentListServices"
AGENT_ASK              = "GoFRAgentAsk"
AGENT_RESET_SESSION    = "GoFRAgentResetSession"
AGENT_REGISTER_SERVICE = "GoFRAgentRegisterService"
AGENT_REFRESH_SERVICES = "GoFRAgentRefreshServices"

# ── downstream tool prefix convention ────────────────────────────────
# Full activity: MCPServer<ServiceName>Tool<ToolName>
# Constructed at runtime — no static constant needed.

ALL_ACTIVITIES: list[str] = [
    AGENT_PING,
    AGENT_LIST_SERVICES,
    AGENT_ASK,
    AGENT_RESET_SESSION,
    AGENT_REGISTER_SERVICE,
    AGENT_REFRESH_SERVICES,
]


# ── helpers ───────────────────────────────────────────────────────────

def parse_authorised_activities(raw: str) -> set[str]:
    """Parse a comma-separated activity string into a set."""
    return {item.strip() for item in raw.split(",") if item.strip()}


def is_authorised(auth_service: object, token: str, required_activity: str) -> bool:
    """Return True if *token* grants *required_activity*."""
    from app.auth.auth_service import AuthService  # noqa: PLC0415
    assert isinstance(auth_service, AuthService)
    raw = auth_service.authorised_activities(token)
    return required_activity in parse_authorised_activities(raw)


def require_activity(
    auth_service: object,
    token: str,
    required_activity: str,
) -> None:
    """Raise :exc:`AuthorizationError` if *token* does not grant *required_activity*."""
    if not is_authorised(auth_service, token, required_activity):
        raise AuthorizationError(required_activity)


def downstream_activity(service_name: str, tool_name: str) -> str:
    """Derive the expected downstream activity string.

    Convention: ``MCPServer<ServiceName>Tool<ToolName>``
    Both parts are title-cased; hyphens and underscores are removed.

    Examples::

        downstream_activity("rag", "search")     → "MCPServerRagToolSearch"
        downstream_activity("my-svc", "my_tool") → "MCPServerMySvcToolMyTool"
    """
    def _title(s: str) -> str:
        return s.replace("-", " ").replace("_", " ").title().replace(" ", "")

    return f"MCPServer{_title(service_name)}Tool{_title(tool_name)}"
```

**Tests:** `tests/unit/test_auth_permissions.py`

```python
import pytest
from app.auth.permissions import (
    parse_authorised_activities,
    is_authorised,
    require_activity,
    downstream_activity,
    AGENT_ASK,
)
from app.exceptions import AuthorizationError


# ── helpers used in tests ─────────────────────────────────────────────
class _FixedAuth:
    def __init__(self, activities: str) -> None:
        self._activities = activities
    def authorised_activities(self, token: str) -> str:
        return self._activities


# ── parse_authorised_activities ───────────────────────────────────────
def test_parse_empty():
    assert parse_authorised_activities("") == set()

def test_parse_single():
    assert parse_authorised_activities("GoFRAgentAsk") == {"GoFRAgentAsk"}

def test_parse_multiple():
    result = parse_authorised_activities("GoFRAgentAsk,GoFRAgentListServices")
    assert result == {"GoFRAgentAsk", "GoFRAgentListServices"}

def test_parse_strips_whitespace():
    result = parse_authorised_activities("  GoFRAgentAsk , GoFRAgentListServices  ")
    assert result == {"GoFRAgentAsk", "GoFRAgentListServices"}


# ── is_authorised ─────────────────────────────────────────────────────
def test_is_authorised_true():
    svc = _FixedAuth("GoFRAgentAsk,GoFRAgentListServices")
    assert is_authorised(svc, "tok", "GoFRAgentAsk") is True

def test_is_authorised_false():
    svc = _FixedAuth("GoFRAgentListServices")
    assert is_authorised(svc, "tok", "GoFRAgentAsk") is False

def test_is_authorised_empty_activities():
    svc = _FixedAuth("")
    assert is_authorised(svc, "tok", "GoFRAgentAsk") is False


# ── require_activity ──────────────────────────────────────────────────
def test_require_activity_passes():
    svc = _FixedAuth("GoFRAgentAsk")
    require_activity(svc, "tok", "GoFRAgentAsk")  # must not raise

def test_require_activity_raises():
    svc = _FixedAuth("")
    with pytest.raises(AuthorizationError) as exc_info:
        require_activity(svc, "tok", "GoFRAgentAsk")
    assert exc_info.value.required_activity == "GoFRAgentAsk"


# ── downstream_activity ───────────────────────────────────────────────
def test_downstream_activity_simple():
    assert downstream_activity("rag", "search") == "MCPServerRagToolSearch"

def test_downstream_activity_hyphenated_service():
    assert downstream_activity("my-svc", "my_tool") == "MCPServerMySvcToolMyTool"

def test_downstream_activity_uppercase_input():
    assert downstream_activity("RAG", "Search") == "MCPServerRagToolSearch"
```

**Verify:** `uv run python -m pytest tests/unit/test_auth_permissions.py -v`

---

### Step A.5 — Bearer token extractor in `app/auth/token.py`

**Why:** Isolates the "get token from request context" concern so it is easy to test and swap.

**Deliverables:** `app/auth/token.py`

```python
"""Utilities for extracting a bearer token from HTTP headers."""
from __future__ import annotations

from app.exceptions import AuthTokenInvalidError


def extract_bearer_token(headers: dict[str, str]) -> str:
    """Return the raw JWT from an *Authorization: Bearer <jwt>* header.

    *headers* is a plain dict with case-insensitive lookup attempted via
    lowercase key first, then ``Authorization`` key.

    Raises :exc:`AuthTokenInvalidError` if the header is missing or malformed.
    """
    raw = headers.get("authorization") or headers.get("Authorization", "")
    if not raw:
        raise AuthTokenInvalidError("Missing Authorization header.")
    parts = raw.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise AuthTokenInvalidError(
            f"Malformed Authorization header: expected 'Bearer <token>', got {raw!r}."
        )
    return parts[1].strip()
```

**Tests:** `tests/unit/test_auth_token.py`

```python
import pytest
from app.auth.token import extract_bearer_token
from app.exceptions import AuthTokenInvalidError


def test_valid_bearer():
    assert extract_bearer_token({"authorization": "Bearer my-jwt"}) == "my-jwt"

def test_valid_bearer_mixed_case_key():
    assert extract_bearer_token({"Authorization": "Bearer my-jwt"}) == "my-jwt"

def test_missing_header_raises():
    with pytest.raises(AuthTokenInvalidError):
        extract_bearer_token({})

def test_wrong_scheme_raises():
    with pytest.raises(AuthTokenInvalidError):
        extract_bearer_token({"authorization": "Basic abc"})

def test_empty_token_raises():
    with pytest.raises(AuthTokenInvalidError):
        extract_bearer_token({"authorization": "Bearer "})

def test_no_space_raises():
    with pytest.raises(AuthTokenInvalidError):
        extract_bearer_token({"authorization": "Bearermy-jwt"})
```

**Verify:** `uv run python -m pytest tests/unit/test_auth_token.py -v`

---

### Step A.6 — `DummyAuthService` test helper

**Why:** Tests need a predictable, injectable `AuthService` implementation.  
This lives in `tests/helpers/` (not in `app/`) and is never imported by production code.

**Deliverables:** `tests/helpers/__init__.py` (empty or existing), `tests/helpers/dummy_auth_service.py`

```python
"""Predictable AuthService stub for unit and integration tests.

Two fixed tokens are recognised:

``dev-admin-token``
    Grants all gofr-agent activities plus a broad set of downstream activities.

``dev-read-token``
    Grants read-only agent activities (ping, list_services, ask) only.

Any other token → empty string (denied).
"""
from __future__ import annotations

from app.auth.permissions import (
    AGENT_ASK,
    AGENT_LIST_SERVICES,
    AGENT_PING,
    AGENT_REFRESH_SERVICES,
    AGENT_REGISTER_SERVICE,
    AGENT_RESET_SESSION,
)

_ADMIN_ACTIVITIES = ",".join([
    AGENT_PING,
    AGENT_LIST_SERVICES,
    AGENT_ASK,
    AGENT_RESET_SESSION,
    AGENT_REGISTER_SERVICE,
    AGENT_REFRESH_SERVICES,
    # Broad downstream grant for tests — real impl would be per-tool
    "MCPServerRagToolSearch",
    "MCPServerDocsDataRead",
    "MCPServerSandboxExecute",
])

_READ_ACTIVITIES = ",".join([
    AGENT_PING,
    AGENT_LIST_SERVICES,
    AGENT_ASK,
])

_TOKEN_MAP: dict[str, str] = {
    "dev-admin-token": _ADMIN_ACTIVITIES,
    "dev-read-token": _READ_ACTIVITIES,
}


class DummyAuthService:
    """Predictable AuthService implementation for tests."""

    def authorised_activities(self, token: str) -> str:
        return _TOKEN_MAP.get(token, "")
```

**Tests:** `tests/unit/test_dummy_auth_service.py`

```python
from tests.helpers.dummy_auth_service import DummyAuthService
from app.auth.auth_service import AuthService
from app.auth.permissions import (
    AGENT_ASK,
    AGENT_LIST_SERVICES,
    AGENT_REGISTER_SERVICE,
    parse_authorised_activities,
)


def test_satisfies_protocol():
    assert isinstance(DummyAuthService(), AuthService)


def test_admin_token_grants_all_agent_activities():
    svc = DummyAuthService()
    activities = parse_authorised_activities(svc.authorised_activities("dev-admin-token"))
    assert AGENT_ASK in activities
    assert AGENT_REGISTER_SERVICE in activities


def test_read_token_grants_ask_not_register():
    svc = DummyAuthService()
    activities = parse_authorised_activities(svc.authorised_activities("dev-read-token"))
    assert AGENT_ASK in activities
    assert AGENT_REGISTER_SERVICE not in activities


def test_unknown_token_returns_empty():
    svc = DummyAuthService()
    assert svc.authorised_activities("not-a-real-token") == ""


def test_empty_token_returns_empty():
    svc = DummyAuthService()
    assert svc.authorised_activities("") == ""
```

**Verify:** `uv run python -m pytest tests/unit/test_dummy_auth_service.py -v`

---

### Step A.7 — Update `app/auth/__init__.py`

**Why:** Replace the gofr-common re-exports with the new local interface.

**Deliverables:** replace `app/auth/__init__.py`

```python
"""Auth package — public surface."""
from __future__ import annotations

from app.auth.auth_service import AuthService, get_auth_service
from app.auth.permissions import (
    AGENT_ASK,
    AGENT_LIST_SERVICES,
    AGENT_PING,
    AGENT_REFRESH_SERVICES,
    AGENT_REGISTER_SERVICE,
    AGENT_RESET_SESSION,
    ALL_ACTIVITIES,
    downstream_activity,
    is_authorised,
    parse_authorised_activities,
    require_activity,
)
from app.auth.token import extract_bearer_token

__all__ = [
    "AuthService",
    "get_auth_service",
    "AGENT_ASK",
    "AGENT_LIST_SERVICES",
    "AGENT_PING",
    "AGENT_REFRESH_SERVICES",
    "AGENT_REGISTER_SERVICE",
    "AGENT_RESET_SESSION",
    "ALL_ACTIVITIES",
    "downstream_activity",
    "extract_bearer_token",
    "is_authorised",
    "parse_authorised_activities",
    "require_activity",
]
```

**Tests:** `tests/unit/test_auth_package.py`

```python
"""Smoke-test that the auth package public surface is importable."""
from app.auth import (
    AuthService,
    get_auth_service,
    AGENT_ASK,
    downstream_activity,
    extract_bearer_token,
    require_activity,
)

def test_all_symbols_importable():
    assert callable(get_auth_service)
    assert callable(extract_bearer_token)
    assert callable(require_activity)
    assert callable(downstream_activity)
    assert AGENT_ASK == "GoFRAgentAsk"
```

**Phase A full verify:**

```bash
uv run ruff check app tests scripts
uv run python -m pytest tests/unit/test_auth_errors.py tests/unit/test_auth_service_protocol.py tests/unit/test_auth_permissions.py tests/unit/test_auth_token.py tests/unit/test_dummy_auth_service.py tests/unit/test_auth_package.py -v
```

All 131 existing tests must still pass:

```bash
uv run python -m pytest tests/unit/ -q
```

---

## Phase B0 — Prove MCP Header Extraction

> **Goal:** Confirm the exact supported way to read `Authorization` from a live FastMCP streamable HTTP tool request before changing all handlers.

### Step B0.1 — Live header extraction spike

**Why:** The plan must not depend on an unverified FastMCP internals path. The installed
`Context` type exposes `request_context`, but the exact HTTP request/header object should
be proved by a live test. The repo also has `gofr_common.web.AuthHeaderMiddleware` and
`get_auth_header_from_context()`, which may be the more stable mechanism.

**Deliverables:** one temporary or committed test, `tests/integration/test_auth_header_extraction.py`.

Test both candidate approaches if possible:

1. `ctx.request_context.request.headers` from an injected FastMCP `Context`.
2. `gofr_common.web.AuthHeaderMiddleware` + `get_auth_header_from_context()` wrapped around `mcp.streamable_http_app()`.

Keep the approach that passes against a real `streamablehttp_client(..., headers={...})` call, and delete or mark the losing approach as an implementation note.

**Acceptance:** a live FastMCP tool called over streamable HTTP can return the exact header value `Bearer dev-admin-token`.

**Verify:**

```bash
uv run python -m pytest tests/integration/test_auth_header_extraction.py -v
```

---

## Phase B — Enforce Auth in the MCP Server

> **Goal:** `create_mcp_server()` accepts an `AuthService` and enforces authorization before every tool handler.  
> **Phase checkpoint:** `uv run python -m pytest tests/unit/test_mcp_server.py -q` — all existing + new auth cases green.

---

### Step B.1 — Add `AuthService` parameter to `create_mcp_server()`

**File:** `app/mcp_server/mcp_server.py`

**Changes:**

1. Add import: `from app.auth import AuthService, extract_bearer_token, require_activity` and the activity constants.
2. Add `auth_service: AuthService` as the last positional parameter to `create_mcp_server()`.
3. For each FastMCP tool handler, use the header-extraction mechanism proven in Phase B0 and call `require_activity` before doing any work.

**Token extraction in FastMCP:**  
Use the Phase B0-proven implementation. If direct `Context` access is proven, extract with:

```python
headers = dict(ctx.request_context.request.headers)
token = extract_bearer_token(headers)
```

If middleware/contextvar is proven instead, wrap `mcp.streamable_http_app()` in
`AuthHeaderMiddleware` at startup and parse `get_auth_header_from_context()` inside each
tool handler.

**Activity mapping:**

| Tool | Required activity |
|---|---|
| `ping` | `AGENT_PING` |
| `list_services` | `AGENT_LIST_SERVICES` |
| `ask` | `AGENT_ASK` |
| `reset_session` | `AGENT_RESET_SESSION` |
| `register_service` | `AGENT_REGISTER_SERVICE` |
| `refresh_services` | `AGENT_REFRESH_SERVICES` |

**Error translation:**  
Wrap `AuthorizationError`, `AuthTokenInvalidError`, and `AuthServiceUnavailableError` in an MCP-friendly response. Token errors and denied activities fail closed. Auth service outages also fail closed, with a distinct message so operators can distinguish denial from backend failure.

```python
from mcp import McpError, ErrorData
from mcp.types import INVALID_PARAMS

try:
    token = extract_bearer_token(headers)
    require_activity(auth_service, token, AGENT_PING)
except (AuthTokenInvalidError, AuthorizationError) as exc:
    raise McpError(ErrorData(code=INVALID_PARAMS, message=str(exc))) from exc
except AuthServiceUnavailableError as exc:
    raise McpError(ErrorData(code=INVALID_PARAMS, message="Auth service unavailable")) from exc
```

**Deliverables:** updated `app/mcp_server/mcp_server.py` — signature change + 6 tool guards.

**Tests:** `tests/unit/test_mcp_server.py` — extend the existing test file with:

```python
# ── helpers ───────────────────────────────────────────────────────────
class _AllowAll:
    def authorised_activities(self, token: str) -> str:
        return ",".join(ALL_ACTIVITIES + ["MCPServerRagToolSearch"])

class _DenyAll:
    def authorised_activities(self, token: str) -> str:
        return ""

def _make_ctx(token: str | None = "dev-admin-token") -> MagicMock:
    """Build a minimal FastMCP Context mock."""
    ctx = MagicMock()
    if token:
        ctx.request_context.request.headers = {"authorization": f"Bearer {token}"}
    else:
        ctx.request_context.request.headers = {}
    return ctx

# ── ping ──────────────────────────────────────────────────────────────
async def test_ping_allowed():
    mcp = create_mcp_server(
        _make_config(), _make_registry(), _make_agent(), _make_store(), auth_service=_AllowAll()
    )
    result = await _call_tool(mcp, "ping", ctx=_make_ctx())
    assert result["status"] == "ok"

async def test_ping_denied_no_token():
    mcp = create_mcp_server(
        _make_config(), _make_registry(), _make_agent(), _make_store(), auth_service=_AllowAll()
    )
    with pytest.raises(McpError):
        await _call_tool(mcp, "ping", ctx=_make_ctx(token=None))

async def test_ping_denied_insufficient_activity():
    mcp = create_mcp_server(
        _make_config(), _make_registry(), _make_agent(), _make_store(), auth_service=_DenyAll()
    )
    with pytest.raises(McpError):
        await _call_tool(mcp, "ping", ctx=_make_ctx())

# ── ask ───────────────────────────────────────────────────────────────
async def test_ask_denied_when_activity_missing():
    mcp = create_mcp_server(
        _make_config(), _make_registry(), _make_agent(), _make_store(), auth_service=_DenyAll()
    )
    with pytest.raises(McpError):
        await _call_tool(mcp, "ask", question="hi", ctx=_make_ctx())
```

> Note: existing `test_mcp_server.py` tests need updating to pass `auth_service=_AllowAll()` to `create_mcp_server()`.  
> Add that in the same commit so the test file stays consistent. The examples above use the existing `_make_config()`, `_make_registry()`, `_make_agent()`, and `_make_store()` helpers directly.

The current `_call_tool` helper already accepts keyword arguments:

```python
async def _call_tool(mcp, tool_name: str, **kwargs):
    tool = mcp._tool_manager._tools[tool_name]
    return await tool.fn(**kwargs)
```

Do not pass a positional params dict to `_call_tool`; pass tool parameters as keywords.

**Verify:**

```bash
uv run ruff check app tests scripts
uv run python -m pytest tests/unit/test_mcp_server.py -v
```

---

### Step B.2 — Update `main_mcp.py` to inject `AuthService`

**File:** `app/main_mcp.py`

**Changes:**

1. Import `get_auth_service` from `app.auth`.
2. After building the registry, call `auth_service = get_auth_service()`.
3. Pass `auth_service` to `create_mcp_server(...)`.
4. Remove the `--no-auth` argument.
5. Remove `require_auth` from `GofrAgentConfig` in the same phase, or at minimum stop reading it anywhere. Auth is always on; dev mode still requires a fixed dev token.

**Deliverables:** updated `app/main_mcp.py`.

**Tests:** no new test file — covered by the existing `test_main_mcp.py` smoke test once `auth_service` is injected. Update that test to pass a `DummyAuthService` if needed.

**Verify:**

```bash
uv run ruff check app tests scripts
uv run python -m pytest tests/unit/ -q
```

---

## Phase C — Token Propagation to Downstream Tools

> **Goal:** The user JWT extracted in the MCP tool handler is forwarded through `GofrAgent.run()` → `make_tool()` → `SessionPool.open_user_session()` → downstream MCP call HTTP header.  
> **Phase checkpoint:** `uv run python -m pytest tests/unit/test_tool_factory.py tests/unit/test_agent.py -v` green.

---

### Step C.1 — Thread `token` through `GofrAgent.run()`

**File:** `app/agent/agent.py`

**Changes:**

1. Add `token: str` parameter to `GofrAgent.run(question, session, *, token, ...)`.
2. Pass `token` to every `make_tool(pool, info, max_chars, token=token)` call inside `build()`.

Wait — `build()` pre-builds tools once; it cannot capture a per-request token.  
**Better approach:** rebuild tools lazily per `run()` call, or pass the token as a pydantic-ai dependency.

**Recommended design:** use `pydantic_ai.Agent` with a typed `RunContext[str]` dependency (dependency = the token string), so tool functions can access the token at call time without rebuilding the agent.

Revised flow:

```python
# agent.py
self._agent: Agent[str, str]  # deps type = str (the token)

# in build():
tools = [make_tool(pool, info, max_chars) for ...]
self._agent = Agent(..., tools=tools, deps_type=str)

# in run():
result = await self._agent.run(question, deps=token, ...)
```

```python
# tool_factory.py
async def _call(ctx: RunContext[str], **kwargs: Any) -> str:
    token = ctx.deps
    async with pool.open_user_session(token) as session:
        result = await session.call_tool(info.name, kwargs)
    ...
```

**Deliverables:** updated `app/agent/agent.py` — `run()` gains `token: str` parameter; `Agent` uses `deps_type=str`.

**Tests:** `tests/unit/test_agent.py` — extend existing:

```python
async def test_run_passes_token_to_tools(registry_with_stub_pool):
    """Token passed to run() is forwarded to downstream user sessions."""
    config = GofrAgentConfig(llm_model="test")
    agent = GofrAgent(config, registry_with_stub_pool)
    agent.build()
    result = await agent.run("hello", session, token="dev-admin-token")
    # pool.open_user_session should have been called with the token
    registry_with_stub_pool.stub_pool.assert_open_user_session_called_with_token("dev-admin-token")
```

**Verify:** `uv run python -m pytest tests/unit/test_agent.py -v`

Also update every existing `agent.run(...)` test call to pass `token="dev-admin-token"`, or provide a small `_run_agent(...)` helper in the test file so the new required argument is not missed.

---

### Step C.2 — Thread `token` through `make_tool()` and a user-scoped session opener

**Files:** `app/agent/tool_factory.py`, `app/services/pool.py`

#### `tool_factory.py`

**Changes:**

1. `_call` function signature becomes `async def _call(ctx: RunContext[str], **kwargs) -> str:`.
2. Extract `token = ctx.deps` inside `_call`.
3. Before opening a downstream session, check downstream activity:

```python
from app.auth.permissions import downstream_activity, require_activity

activity = downstream_activity(info.service_name, info.name)
# Inject auth_service via closure from make_tool() parameter
require_activity(auth_service, token, activity)
```

4. Pass `token` to `pool.open_user_session(token)`.

`make_tool()` signature becomes:

```python
def make_tool(
    pool: SessionPool,
    info: MCPToolInfo,
    auth_service: AuthService,
    max_chars: int = 8000,
) -> Tool:
```

#### `pool.py`

**Do not mutate a checked-out `ClientSession` or attach `session._token`.**
`ClientSession.call_tool()` does not accept per-call headers, and mutating SDK objects is brittle.

Keep the existing persistent pool behavior for service-token/background use, and add a separate
one-shot user-session method for user-driven downstream tool calls. This makes the behavioral
change explicit and avoids silently invalidating pool-size, semaphore, health, and reconnect tests.

Recommended API:

```python
@asynccontextmanager
async def open_user_session(self, token: str) -> AsyncIterator[ClientSession]:
    """Open a one-shot session using the user's Authorization header."""
    headers: dict[str, str] = {}
    if not token:
        raise AuthTokenInvalidError("Missing downstream user token.")
    headers["Authorization"] = f"Bearer {token}"

    async with (
        streamablehttp_client(self._service.url, headers=headers) as (r, w, _),
        ClientSession(r, w) as session,
    ):
        await session.initialize()
        yield session
```

`checkout()` remains unchanged in this phase. A later performance phase can decide whether to
replace or extend the persistent pool design for authenticated per-user traffic.

**Deliverables:** updated `app/agent/tool_factory.py`, updated `app/services/pool.py`.

**Tests:** `tests/unit/test_tool_factory.py` — extend existing:

```python
async def test_downstream_activity_checked_before_call():
    """require_activity must fire before checkout."""
    auth = DummyAuthService()  # read token denies MCPServerRagToolSearch
    info = MCPToolInfo(service_name="rag", name="search", description="", input_schema={})

    tool = make_tool(pool=stub_pool, info=info, auth_service=auth, max_chars=100)

    # Simulate RunContext[str] with a read-only token
    ctx = MagicMock(deps="dev-read-token")
    with pytest.raises(AuthorizationError):
        await tool.function(ctx, query="hello")


async def test_downstream_activity_allowed_calls_tool():
    auth = DummyAuthService()
    info = MCPToolInfo(service_name="rag", name="search", description="", input_schema={})

    tool = make_tool(pool=stub_pool, info=info, auth_service=auth, max_chars=100)
    ctx = MagicMock(deps="dev-admin-token")
    result = await tool.function(ctx, query="hello")
    assert isinstance(result, str)
```

If `Tool.function(ctx, ...)` does not match pydantic-ai's public calling convention after the implementation, replace these with a small real-Agent test that invokes the tool through `Agent(..., deps_type=str)` and `run_stream(..., deps="dev-admin-token")`. Do not test private `tool._func` internals.

**Tests:** `tests/unit/test_pool.py` — extend existing:

```python
async def test_open_user_session_uses_token_header(mock_streamablehttp):
    """Token passed to open_user_session is sent as Authorization header."""
    pool = SessionPool(service_config, pool_size=1)
    async with pool.open_user_session("my-jwt") as session:
        pass
    called_headers = mock_streamablehttp.call_args.kwargs["headers"]
    assert called_headers["Authorization"] == "Bearer my-jwt"

async def test_checkout_semantics_are_unchanged(mock_streamablehttp):
    svc = ServiceConfig(name="svc", url="http://x", token="svc-token")
    pool = SessionPool(svc, pool_size=1)
    # Existing checkout behavior is covered by current pool tests; this test asserts
    # adding open_user_session did not replace checkout semantics.
    assert hasattr(pool, "checkout")
```

**Verify:**

```bash
uv run ruff check app tests scripts
uv run python -m pytest tests/unit/test_tool_factory.py tests/unit/test_pool.py tests/unit/test_agent.py -v
```

---

### Step C.3 — Update `GofrAgent.build()` to pass `auth_service`

**File:** `app/agent/agent.py`

**Changes:**

1. `GofrAgent.__init__` gains `auth_service: AuthService`.
2. `build()` passes `auth_service` to every `make_tool(pool, info, auth_service, max_chars)` call.

**Deliverables:** updated `app/agent/agent.py`.

**Tests:** update `tests/unit/test_agent.py` — `GofrAgent(config, registry, auth_service=DummyAuthService())`.

---

### Step C.4 — Pass the extracted token from MCP `ask` into `GofrAgent.run()`

**File:** `app/mcp_server/mcp_server.py`

**Changes:**

1. In the `ask` handler, extract the bearer token once.
2. Use that token for `require_activity(auth_service, token, AGENT_ASK)`.
3. Pass the same raw token into `agent.run(..., token=token)`.

**Tests:** extend `tests/unit/test_mcp_server.py`:

```python
async def test_ask_passes_user_token_to_agent():
    agent = _make_agent()
    mcp = create_mcp_server(
        _make_config(), _make_registry(), agent, _make_store(), auth_service=_AllowAll()
    )

    await _call_tool(mcp, "ask", question="hi", ctx=_make_ctx("dev-admin-token"))

    agent.run.assert_awaited_once()
    assert agent.run.await_args.kwargs["token"] == "dev-admin-token"
```

**Phase C full verify:**

```bash
uv run ruff check app tests scripts
uv run python -m pytest tests/unit/ -q
```

All 131 + Phase A + Phase B tests must pass.

---

## Phase D — CLI Token Support

> **Goal:** CLI can supply a JWT via `--token` or `GOFR_AGENT_TOKEN`; token is sent in `Authorization: Bearer` header.  
> **Phase checkpoint:** `uv run python -m pytest tests/unit/test_cli.py -v` all green.

---

### Step D.1 — Add `--token` option to `app/cli/ask.py`

**File:** `app/cli/ask.py`

**Changes:**

1. Add `--token` / `GOFR_AGENT_TOKEN`:

```python
token: str = typer.Option(
    os.environ.get("GOFR_AGENT_TOKEN", ""),
    "--token",
    help="JWT bearer token for authentication.",
)
```

2. Remove `--no-auth` (it was already a no-op; removing it enforces the "auth always on" principle).

3. Pass `token` to `_run()` and forward as `Authorization: Bearer <token>` header on the `streamablehttp_client` call:

```python
async with (
    streamablehttp_client(
        url,
        headers={"Authorization": f"Bearer {token}"} if token else {},
    ) as (read, write, _),
    ClientSession(read, write) as client,
):
```

4. If no `--token` provided and `GOFR_AGENT_TOKEN` is empty, print a clear error and exit:

```python
if not token:
    typer.echo("Error: --token or GOFR_AGENT_TOKEN is required.", err=True)
    raise typer.Exit(code=1)
```

**Deliverables:** updated `app/cli/ask.py`.

**Tests:** `tests/unit/test_cli.py` — extend existing:

```python
def test_ask_sends_token_header(mock_streamablehttp_client):
    runner = CliRunner()
    result = runner.invoke(app, ["--token", "my-jwt", "Hello"])
    call_headers = mock_streamablehttp_client.call_args.kwargs["headers"]
    assert call_headers["Authorization"] == "Bearer my-jwt"


def test_ask_token_from_env(mock_streamablehttp_client, monkeypatch):
    monkeypatch.setenv("GOFR_AGENT_TOKEN", "env-jwt")
    runner = CliRunner()
    result = runner.invoke(app, ["Hello"])
    call_headers = mock_streamablehttp_client.call_args.kwargs["headers"]
    assert call_headers["Authorization"] == "Bearer env-jwt"


def test_ask_no_token_exits_with_error():
    runner = CliRunner()
    result = runner.invoke(app, ["Hello"])
    assert result.exit_code != 0
    assert "token" in result.output.lower() or "GOFR_AGENT_TOKEN" in result.output
```

**Verify:**

```bash
uv run ruff check app tests scripts
uv run python -m pytest tests/unit/test_cli.py -v
```

---

## Phase E — Integration Tests

> **Goal:** Full end-to-end test with a live `gofr-agent` MCP server using `DummyAuthService`. Verifies allowed and denied paths at the HTTP level.  
> **Phase checkpoint:** `uv run python -m pytest tests/ -q` — full suite green.

---

### Step E.1 — Auth-aware integration test fixture

**File:** `tests/integration/conftest.py` — add fixture:

```python
@pytest_asyncio.fixture
async def auth_mcp_server(tmp_path):
    """Spin up a gofr-agent MCP server with DummyAuthService."""
    from tests.helpers.dummy_auth_service import DummyAuthService

    config = GofrAgentConfig(llm_model="test")
    registry = ServiceRegistry(config)
    agent = GofrAgent(config, registry, auth_service=DummyAuthService())
    agent.build()
    session_store = SessionStore(ttl_minutes=5)

    mcp = create_mcp_server(config, registry, agent, session_store,
                            auth_service=DummyAuthService())

    # Start server on a random port
    port = find_free_port()
    server_task = asyncio.create_task(_run_mcp(mcp, port))
    await asyncio.sleep(0.2)  # let server bind
    yield f"http://localhost:{port}/mcp"
    server_task.cancel()
```

---

### Step E.2 — Integration tests for allowed paths

**File:** `tests/integration/test_auth_integration.py`

```python
"""Integration tests — auth enforcement on a live gofr-agent server."""
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def _call(url: str, tool: str, params: dict, token: str):
    headers = {"Authorization": f"Bearer {token}"}
    async with (
        streamablehttp_client(url, headers=headers) as (r, w, _),
        ClientSession(r, w) as client,
    ):
        await client.initialize()
        return await client.call_tool(tool, params)


# ── admin token: allowed ──────────────────────────────────────────────
async def test_ping_allowed_with_admin_token(auth_mcp_server):
    result = await _call(auth_mcp_server, "ping", {}, token="dev-admin-token")
    assert result.content

async def test_list_services_allowed_with_admin_token(auth_mcp_server):
    result = await _call(auth_mcp_server, "list_services", {}, token="dev-admin-token")
    assert result.content

async def test_ask_allowed_with_admin_token(auth_mcp_server):
    result = await _call(auth_mcp_server, "ask", {"question": "hi"}, token="dev-admin-token")
    assert result.content


# ── read token: partial access ────────────────────────────────────────
async def test_ask_allowed_with_read_token(auth_mcp_server):
    result = await _call(auth_mcp_server, "ask", {"question": "hi"}, token="dev-read-token")
    assert result.content

async def test_register_denied_with_read_token(auth_mcp_server):
    """read token does not grant GoFRAgentRegisterService."""
    from mcp import McpError
    with pytest.raises(McpError):
        await _call(
            auth_mcp_server,
            "register_service",
            {"name": "x", "url": "http://x"},
            token="dev-read-token",
        )


# ── no token: denied ─────────────────────────────────────────────────
async def test_ping_denied_without_token(auth_mcp_server):
    from mcp import McpError
    async with (
        streamablehttp_client(auth_mcp_server) as (r, w, _),
        ClientSession(r, w) as client,
    ):
        await client.initialize()
        with pytest.raises(McpError):
            await client.call_tool("ping", {})


# ── unknown token: denied ─────────────────────────────────────────────
async def test_ping_denied_with_unknown_token(auth_mcp_server):
    from mcp import McpError
    with pytest.raises(McpError):
        await _call(auth_mcp_server, "ping", {}, token="not-a-real-token")
```

---

### Step E.3 — Integration test for downstream token propagation

**File:** `tests/integration/test_auth_integration.py` — add section:

```python
# ── downstream token forwarding ───────────────────────────────────────
async def test_downstream_tool_call_forwards_token(
    auth_mcp_server_with_mock_downstream,
):
    """When ask triggers a tool call, the user token appears in the downstream request."""
    result = await _call(
        auth_mcp_server_with_mock_downstream.url,
        "ask",
        {"question": "search for docs"},
        token="dev-admin-token",
    )
    # Inspect what the mock downstream received
    received_headers = auth_mcp_server_with_mock_downstream.last_request_headers
    assert received_headers.get("authorization") == "Bearer dev-admin-token"
```

> The `auth_mcp_server_with_mock_downstream` fixture spins up both gofr-agent and a mock downstream FastMCP server (reuse `mock_mcp_server.py` from Phase 10).

Make this deterministic. Do not rely on a real LLM deciding to call a tool. Use one of these approaches:

1. A `TestModel`/pydantic-ai setup explicitly configured to call the mock downstream tool.
2. A lower-level integration test that invokes the generated pydantic-ai tool function with `deps="dev-admin-token"` against a live mock downstream server.

Also update the mock downstream fixture to capture the incoming `authorization` header using the Phase B0-proven extraction method.

---

### Step E.4 — Run full suite

```bash
uv run ruff check app tests scripts
uv run python -m pytest tests/ -q
```

Expected: all 131 existing tests + ~20 new auth tests green.

---

## Phase F — Cleanup and Hardening (optional, after all above)

These are improvements to be done after the core auth flow is verified.

| Item | Description |
|---|---|
| F.1 | Remove any remaining dead compatibility references to old auth behavior after Phase B/D migration |
| F.2 | Remove `DevAuthService` from `app/auth/` and make `get_auth_service()` raise `NotImplementedError` with a message pointing to the docs — forces explicit injection in tests and production |
| F.3 | Add structured logging on every auth decision (allowed / denied / error) |
| F.4 | Add metrics for allowed / denied / unavailable auth decisions |
| F.5 | Decide whether authenticated per-user traffic needs a persistent pool design beyond `open_user_session()` |

---

## Summary Checklist

| Phase | Deliverable | Tests added |
|---|---|---|
| A.1 | Error types in `app/exceptions/errors.py` | `test_auth_errors.py` |
| A.2 | `AuthService` Protocol in `app/auth/auth_service.py` | `test_auth_service_protocol.py` |
| A.3 | `DevAuthService` in `app/auth/_dev_auth_service.py` | (covered by A.2 test) |
| A.4 | Activity constants + helpers in `app/auth/permissions.py` | `test_auth_permissions.py` |
| A.5 | Token extractor in `app/auth/token.py` | `test_auth_token.py` |
| A.6 | `DummyAuthService` in `tests/helpers/dummy_auth_service.py` | `test_dummy_auth_service.py` |
| A.7 | New `app/auth/__init__.py` | `test_auth_package.py` |
| B0.1 | Live FastMCP header extraction proof | `test_auth_header_extraction.py` |
| B.1 | `create_mcp_server(auth_service=...)` — guards all 6 tools | `test_mcp_server.py` additions |
| B.2 | `main_mcp.py` injects `get_auth_service()` | existing smoke test update |
| C.1 | `GofrAgent.run(token=...)` → `deps_type=str` | `test_agent.py` additions |
| C.2 | `make_tool` downstream activity check + `open_user_session(token)` | `test_tool_factory.py`, `test_pool.py` |
| C.3 | `GofrAgent.__init__(auth_service=...)` | `test_agent.py` update |
| C.4 | `ask` passes extracted token into `GofrAgent.run()` | `test_mcp_server.py` addition |
| D.1 | CLI `--token` / `GOFR_AGENT_TOKEN`, remove `--no-auth` | `test_cli.py` additions |
| E.1–E.4 | Integration tests — live server allowed/denied/forwarding | `test_auth_integration.py` |

**Target test count after all phases:** ≥ 155 (131 existing + ~25 new).
