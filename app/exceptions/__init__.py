"""Custom exceptions for gofr-agent.

Hierarchy:
    GofrAgentError (base)
    ├── ServiceConnectionError  — pool / connection failures
    ├── ToolDiscoveryError      — failed tool list from downstream
    ├── SessionNotFoundError    — unknown session_id supplied by caller
    ├── SessionCapacityError    — session limit reached
    ├── PendingUserInputExistsError — unresolved pending user prompt exists
    ├── ToolResultTruncatedWarning — informational; not raised to callers
    └── ConfigurationError      — invalid startup configuration
"""


class GofrAgentError(Exception):
    """Base exception for all gofr-agent errors."""


class ServiceConnectionError(GofrAgentError):
    """Raised when a connection to a downstream MCP service fails."""


class ToolDiscoveryError(GofrAgentError):
    """Raised when tool list retrieval from a downstream MCP service fails."""


class SessionNotFoundError(GofrAgentError):
    """Raised when a caller supplies an unknown session_id."""


class SessionCapacityError(GofrAgentError):
    """Raised when creating a new session would exceed the session limit."""


class PendingUserInputExistsError(GofrAgentError):
    """Raised when a session already has unresolved pending user input."""


class ServiceRegistrationPolicyError(GofrAgentError):
    """Raised when dynamic service registration violates policy."""


class ToolResultTruncatedWarning(GofrAgentError):
    """Informational: tool result was truncated to fit TOOL_RESULT_MAX_CHARS.

    Not raised to callers; used internally for structured logging.
    """


class ConfigurationError(GofrAgentError):
    """Raised when startup configuration is invalid (e.g. missing JWT secret)."""


class AuthorizationError(GofrAgentError):
    """Raised when a token lacks the required activity."""

    def __init__(self, required_activity: str) -> None:
        super().__init__(f"Not authorized for activity: {required_activity}")
        self.required_activity = required_activity


class AuthServiceError(GofrAgentError):
    """Base error for auth service failures."""


class AuthTokenInvalidError(AuthServiceError):
    """Token is missing, malformed, or rejected by validation."""


class AuthServiceUnavailableError(AuthServiceError):
    """The auth backend cannot answer authorization questions."""


class DownstreamToolError(GofrAgentError):
    """Structured error for a failed downstream tool call."""

    def __init__(
        self,
        *,
        service: str,
        tool: str,
        message: str,
        transient: bool,
        fatal: bool,
        recovery_hint: str | None = None,
        code: str | None = None,
        required_activity: str | None = None,
    ) -> None:
        super().__init__(message)
        self.service = service
        self.tool = tool
        self.message = message
        self.transient = transient
        self.fatal = fatal
        self.recovery_hint = recovery_hint
        self.code = code
        self.required_activity = required_activity

    def as_payload(self) -> dict[str, str | bool | None]:
        payload: dict[str, str | bool | None] = {
            "service": self.service,
            "tool": self.tool,
            "message": self.message,
            "transient": self.transient,
            "fatal": self.fatal,
            "recovery_hint": self.recovery_hint,
        }
        if self.code is not None:
            payload["code"] = self.code
        if self.required_activity is not None:
            payload["required_activity"] = self.required_activity
        return payload
