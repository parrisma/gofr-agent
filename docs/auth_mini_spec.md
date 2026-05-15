# gofr-agent JWT Authorization Mini Spec

> Status: Draft v0.1  
> Date: 2026-05-13  
> Scope: Minimal end-to-end authorization model for gofr-agent and downstream MCP services. This spec defines the expected token flow and authorization checks, not a production-grade identity provider.

---

## 1. Goal

`gofr-agent` and all attached downstream MCP servers must participate in the same simple authorization flow:

1. A user-facing client starts with, or obtains, a JWT token.
2. The client sends that JWT token to `gofr-agent` in the HTTP `Authorization` header.
3. `gofr-agent` checks whether the token is allowed to call the requested agent operation.
4. If the agent needs to call a downstream MCP server, it checks whether the same token is allowed to request that downstream operation.
5. `gofr-agent` forwards the same JWT token to the downstream MCP server in the HTTP `Authorization` header.
6. The downstream MCP server performs its own authorization check before executing the operation or returning data.

For this stage, the authorization decision can be hard-coded and intentionally simple. The important behavior is the contract: the same user token follows the request through the full MCP chain, and every boundary can decide whether the requested operation is legal.

---

## 2. Non-Goals

This mini spec does not require:

- Full login implementation.
- Real user/group/role storage.
- Production-grade policy evaluation.
- Token minting, refresh, revocation, or expiry handling beyond basic JWT parsing if available.
- A final permission naming scheme.
- Cryptographic key rotation.

Those can be layered in later without changing the request propagation contract.

---

## 3. Required Principles

### 3.1 Auth Is Always On

There is no production runtime mode where auth is disabled.

- `gofr-agent` always expects a bearer token for MCP requests.
- Downstream MCP servers always expect a bearer token for incoming MCP requests.
- Local development may use a static test token, but the code path should still include the auth header and authorization checks.

### 3.2 One User Token Per Request Chain

The JWT presented by the client is the same JWT used throughout the request chain.

```text
CLI / UI
  Authorization: Bearer <jwt>
        |
        v
gofr-agent MCP
  Authorization: Bearer <same jwt>
        |
        v
Downstream MCP server(s)
```

`gofr-agent` must not replace the user token with a service token when calling downstream MCP servers for user-driven work. If service-to-service credentials are needed later, they should be additive and distinguishable from the user JWT.

### 3.3 Every Boundary Authorizes Independently

Each MCP boundary checks authorization for the operation it is about to perform.

- `gofr-agent` checks whether the caller can use the agent operation.
- `gofr-agent` checks whether it is allowed to route the user's request to a downstream MCP operation.
- The downstream MCP server checks whether the token authorizes the specific tool/data access it is about to execute.

---

## 4. Token Input

### 4.1 CLI / UI Startup Token

The CLI or UI must be able to receive a token at startup.

Allowed sources for this stage:

- CLI flag: `--token <jwt>`
- Environment variable: `GOFR_AGENT_TOKEN=<jwt>`
- UI startup config: equivalent token value passed into the UI runtime

Example CLI usage:

```bash
uv run python -m app.cli.ask \
  --token "$GOFR_AGENT_TOKEN" \
  "Summarise the available services"
```

### 4.2 Login Process Placeholder

A future CLI/UI login process may obtain the JWT interactively.

For now, login can be a placeholder that results in a token string available to the client. The rest of the system should not depend on how the token was obtained.

---

## 5. HTTP Header Contract

All MCP HTTP requests carry the JWT using the standard bearer header:

```http
Authorization: Bearer <jwt>
```

Rules:

- Missing header: reject with an auth error.
- Non-bearer header: reject with an auth error.
- Empty token: reject with an auth error.
- Present bearer token: pass token to the auth service for operation checks.

---

## 6. Authorization Activity Strings

Authorization decisions are based on activity strings. An activity string names one operation or data-access capability.

Examples:

```text
GoFRAgentReadWriteUser
GoFRAgentAsk
GoFRAgentListServices
GoFRAgentRegisterService
MCPServerAbcToolCallX
MCPServerRagSearch
MCPServerSandboxExecute
```

The naming scheme is intentionally flexible at this stage. The only required property is that callers and services agree on the exact strings checked.

Suggested convention:

```text
<Domain><Resource><Action>
```

Examples:

```text
GoFRAgentAsk
GoFRAgentSessionReset
MCPServerRagToolSearch
MCPServerDocsDataRead
```

---

## 7. Auth Service Interface

### 7.1 Purpose

Create an auth service interface that accepts a JWT token and returns the list of activities authorized for that token.

This interface is the stable boundary for authorization decisions. Production and future implementations can back it with real policy, claims, groups, roles, or an external authorization system. Tests and early development can provide a hard-coded dummy implementation of the interface.

### 7.2 Interface

Expected Python interface:

```python
from typing import Protocol


class AuthService(Protocol):
    def authorised_activities(self, token: str) -> str:
        """Return authorized activities for a JWT as a comma-separated string."""
```

Required behavior:

| Method | Input | Output | Notes |
|---|---|---|---|
| `authorised_activities(token)` | Raw JWT token string without the `Bearer ` prefix | Comma-separated activity string | Token may be opaque for now; implementation decides how to interpret it |

The returned string is the source of truth for this stage. It must contain zero or more activity names separated by commas:

```text
GoFRAgentReadWriteUser,GoFRAgentAsk,GoFRAgentListServices,MCPServerAbcToolCallX
```

Empty or unauthorized tokens can return an empty string:

```text
""
```

The interface deliberately does not require the auth service to know about MCP request objects, HTTP headers, service names, tool names, or sessions. Callers extract the token, derive the required activity string, and ask the auth service what the token is allowed to do.

### 7.3 Interface Semantics

The auth service must follow these semantics:

| Case | Expected result |
|---|---|
| Known token with permissions | Return comma-separated activities |
| Known token with no permissions | Return empty string |
| Unknown token | Return empty string for this stage |
| Malformed token | Return empty string for this stage, or raise a typed auth error if the implementation supports validation |
| Auth backend unavailable | Raise a typed auth service error |

Suggested support types:

```python
class AuthServiceError(Exception):
    """Base error for auth service failures."""


class AuthTokenInvalidError(AuthServiceError):
    """Token is missing, malformed, or rejected by validation."""


class AuthServiceUnavailableError(AuthServiceError):
    """The auth backend cannot answer authorization questions."""
```

For the first implementation, it is acceptable for the test/dev auth service to avoid raising these errors and simply return `""` for denied tokens.

### 7.4 Convenience Helpers Around the Interface

Runtime code should use helpers around `AuthService` rather than splitting strings everywhere:

```python
def parse_authorised_activities(raw: str) -> set[str]:
    return {item.strip() for item in raw.split(",") if item.strip()}


def is_authorised(
    auth_service: AuthService,
    token: str,
    required_activity: str,
) -> bool:
    activities = parse_authorised_activities(
        auth_service.authorised_activities(token)
    )
    return required_activity in activities


def require_activity(
    auth_service: AuthService,
    token: str,
    required_activity: str,
) -> None:
    if not is_authorised(auth_service, token, required_activity):
        raise PermissionError(required_activity)
```

The concrete exception used by `require_activity()` can be replaced by an app-specific authorization exception during implementation.

### 7.5 Factory / Injection Contract

`gofr-agent` should receive an `AuthService` instance through dependency injection or a small factory:

```python
def get_auth_service() -> AuthService:
    """Return the configured auth service implementation."""
```

Production code depends only on the `AuthService` protocol. Tests can pass a dummy implementation directly.

### 7.6 Test / Development Dummy Implementation

As part of the test code, create a dummy implementation of `AuthService`. For early development this implementation may ignore the token value and return a hard-coded list:

```text
GoFRAgentReadWriteUser,
GoFRAgentAsk,
GoFRAgentListServices,
GoFRAgentResetSession,
MCPServerAbcToolCallX,
MCPServerRagSearch,
MCPServerSandboxExecute
```

Optionally, the test implementation can recognize one or two fixed test tokens:

| Token | Activities |
|---|---|
| `dev-admin-token` | all hard-coded activities |
| `dev-read-token` | read-only activities only |
| anything else | empty list or default dev list, depending on test needs |

---

## 8. gofr-agent Authorization Flow

### 8.1 Incoming MCP Request

When `gofr-agent` receives an MCP request:

1. Extract JWT from `Authorization: Bearer <jwt>`.
2. Determine required activity for the agent-level operation.
3. Ask auth service for authorized activities.
4. If required activity is missing, reject the request.
5. If present, continue.

Example mapping:

| gofr-agent operation | Required activity |
|---|---|
| `ping` | `GoFRAgentPing` or no activity, depending on desired health-check policy |
| `list_services` | `GoFRAgentListServices` |
| `ask` | `GoFRAgentAsk` |
| `reset_session` | `GoFRAgentResetSession` |
| `register_service` | `GoFRAgentRegisterService` |
| `refresh_services` | `GoFRAgentRefreshServices` |

### 8.2 Downstream Routing Check

Before `gofr-agent` calls a downstream MCP tool, it checks whether the original JWT is allowed to route to that downstream operation.

Required downstream activity can be derived from service/tool identity:

```text
MCPServer<ServiceName>Tool<ToolName>
```

Example:

```text
service = "rag"
tool = "search"
required_activity = "MCPServerRagToolSearch"
```

If the required activity is missing, `gofr-agent` must not call the downstream MCP server.

### 8.3 Downstream Call

When `gofr-agent` does call the downstream MCP server, it forwards the original JWT:

```http
Authorization: Bearer <same jwt>
```

The downstream MCP server repeats its own check before executing the tool.

---

## 9. Downstream MCP Server Authorization Flow

When a downstream MCP server receives a request from `gofr-agent`:

1. Extract JWT from `Authorization: Bearer <jwt>`.
2. Determine required activity for the requested MCP tool or data access.
3. Ask auth service for authorized activities.
4. If required activity is missing, reject the request.
5. If present, execute the operation and return data.

This makes downstream servers independently responsible for their own data-access rules.

---

## 10. Minimal Implementation Shape

Suggested modules for `gofr-agent`:

```text
app/auth/
  __init__.py
  auth_service.py
  token.py
  permissions.py
```

Suggested responsibilities:

| Module | Responsibility |
|---|---|
| `auth_service.py` | `AuthService` interface/protocol and production-facing auth service factory |
| `token.py` | Extract bearer token from headers/request context |
| `permissions.py` | Activity naming and `require_activity(...)` helper |

Test-only dummy implementation:

```text
tests/helpers/dummy_auth_service.py
```

The test helper implements the same `AuthService` interface and returns a hard-coded activity list.

Suggested helper behavior:

```python
def require_activity(token: str, required_activity: str) -> None:
    activities = parse_activities(auth_service.authorised_activities(token))
    if required_activity not in activities:
        raise AuthorizationError(required_activity)
```

The exact exception type and MCP error mapping can be decided during implementation.

---

## 11. Request Context Requirement

`gofr-agent` must keep the original JWT available for the full duration of an `ask` call so tool wrappers can use it when calling downstream MCP servers.

Possible approaches:

- Add an auth context object passed through the agent run dependencies.
- Store token in a per-request context variable (`contextvars.ContextVar`).
- Pass token explicitly from MCP tool handler to `GofrAgent.run(...)`, then to generated downstream tools.

Preferred for clarity at this stage: pass token explicitly through the call stack.

---

## 12. Acceptance Criteria

A minimal implementation satisfies this spec when:

1. Auth is always enabled in normal runtime paths.
2. CLI/UI can provide a JWT token at startup or via a placeholder login flow.
3. `gofr-agent` rejects calls that do not include `Authorization: Bearer <jwt>`.
4. `gofr-agent` checks an activity via the auth service before executing each exposed MCP operation.
5. `gofr-agent` checks a downstream activity via the auth service before calling an attached MCP tool.
6. `gofr-agent` forwards the same JWT in the `Authorization` header to downstream MCP servers.
7. Downstream MCP servers can use the same `AuthService` interface to authorize their own tool/data access.
8. Tests cover allowed and denied cases for agent-level calls and downstream tool calls.

---

## 13. Example End-to-End Flow

User asks through CLI:

```bash
uv run python -m app.cli.ask \
  --token dev-admin-token \
  "Search the docs for deployment instructions"
```

Flow:

1. CLI sends `Authorization: Bearer dev-admin-token` to `gofr-agent`.
2. `gofr-agent` checks `GoFRAgentAsk`.
3. Agent decides it needs downstream `rag.search`.
4. `gofr-agent` checks `MCPServerRagToolSearch`.
5. `gofr-agent` calls the RAG MCP server with `Authorization: Bearer dev-admin-token`.
6. RAG MCP server checks `MCPServerRagToolSearch` or a more specific data activity.
7. RAG MCP server returns authorized data.
8. `gofr-agent` answers the user.

If any check fails, the chain stops at that boundary and returns an authorization error.
