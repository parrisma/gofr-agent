"""Base exception classes for GOFR applications.

All GOFR exceptions include structured error information:
- code: Machine-readable error identifier
- message: Human-readable error description
- details: Additional context for debugging/recovery
"""

from typing import Any, Dict, Optional


class GofrError(Exception):
    """Base exception for all GOFR errors.

    Provides structured error information for consistent handling
    across MCP and web interfaces.

    Attributes:
        code: Machine-readable error code (e.g., "INVALID_TABLE_DATA")
        message: Human-readable error message
        details: Optional additional context for debugging/recovery
    """

    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        """Initialize error with structured information.

        Args:
            code: Machine-readable error code (e.g., "INVALID_TABLE_DATA")
            message: Human-readable error message
            details: Optional additional context
        """
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)

    def __str__(self) -> str:
        """Return formatted error string."""
        if self.details:
            return f"{self.code}: {self.message} (details: {self.details})"
        return f"{self.code}: {self.message}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for JSON serialization.

        Returns:
            Dictionary with code, message, and details keys.
        """
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class ValidationError(GofrError):
    """Base for all validation errors.

    Used when input data fails validation rules.
    """

    pass


class ResourceNotFoundError(GofrError):
    """Base for resource not found errors.

    Used when a requested resource (template, session, style, etc.) doesn't exist.
    """

    pass


class SecurityError(GofrError):
    """Base for security and authorization errors.

    Used when access is denied due to group mismatch or authentication failure.
    """

    pass


class ConfigurationError(GofrError):
    """Base for configuration and setup errors.

    Used when system configuration is invalid or incomplete.
    """

    pass


class RegistryError(GofrError):
    """Base exception for registry operations.

    Maintains backward compatibility while adding structured error info.
    The message parameter can be passed as the first positional argument
    for backward compatibility with code that uses `raise RegistryError("message")`.
    """

    def __init__(
        self, message: str, code: str = "REGISTRY_ERROR", details: Optional[Dict[str, Any]] = None
    ):
        """Initialize registry error.

        Args:
            message: Error message (for backward compatibility, can be first arg)
            code: Error code (default: "REGISTRY_ERROR")
            details: Additional context
        """
        super().__init__(code=code, message=message, details=details)
