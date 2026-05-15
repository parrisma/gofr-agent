"""Custom exceptions for gofr-agent.

Hierarchy:
    GofrAgentError (base)
    ├── ServiceConnectionError  — pool / connection failures
    ├── ToolDiscoveryError      — failed tool list from downstream
    ├── SessionNotFoundError    — unknown session_id supplied by caller
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
