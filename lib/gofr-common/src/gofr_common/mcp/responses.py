"""MCP Response formatting utilities.

Provides consistent response formatting for MCP tool handlers across all GOFR projects.
Supports JSON responses, error formatting with recovery strategies, and success/error helpers.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union

from mcp.types import EmbeddedResource, ImageContent, TextContent

# Type aliases for MCP responses
ToolResponse = List[Union[TextContent, ImageContent, EmbeddedResource]]


def _default_serializer(obj: Any) -> Any:
    """Default JSON serializer for non-standard types.

    Handles:
    - Pydantic models (via model_dump)
    - Dataclasses and objects with __dict__
    - Fallback to str() for other types
    """
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)


def json_text(
    data: Dict[str, Any],
    indent: int = 2,
    serializer: Any = None,
) -> TextContent:
    """Create a JSON TextContent response.

    Args:
        data: Dictionary to serialize to JSON
        indent: JSON indentation level (default: 2)
        serializer: Custom JSON serializer function (default: handles Pydantic models)

    Returns:
        TextContent with JSON-formatted text
    """
    return TextContent(
        type="text",
        text=json.dumps(
            data,
            indent=indent,
            ensure_ascii=True,
            default=serializer or _default_serializer,
        ),
    )


def success_response(
    data: Any,
    message: Optional[str] = None,
) -> ToolResponse:
    """Create a standardized success response.

    Args:
        data: The result data to include
        message: Optional success message

    Returns:
        List with single TextContent containing JSON success response
    """
    payload: Dict[str, Any] = {"status": "success", "data": data}
    if message:
        payload["message"] = message
    return [json_text(payload)]


def error_response(
    error_code: str,
    message: str,
    recovery_strategy: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> ToolResponse:
    """Create a standardized error response with recovery strategy.

    Args:
        error_code: Machine-readable error code (e.g., "INVALID_URL", "AUTH_REQUIRED")
        message: Human-readable error message
        recovery_strategy: Suggested action to resolve the error
        details: Optional additional context

    Returns:
        List with single TextContent containing JSON error response
    """
    payload: Dict[str, Any] = {
        "status": "error",
        "error_code": error_code,
        "message": message,
    }

    if recovery_strategy:
        payload["recovery_strategy"] = recovery_strategy

    if details:
        payload["details"] = details

    return [json_text(payload)]


def format_validation_error(
    errors: List[Dict[str, Any]],
    context: Optional[str] = None,
) -> ToolResponse:
    """Format Pydantic validation errors for MCP response.

    Args:
        errors: List of error dicts from PydanticValidationError.errors()
        context: Optional context about what was being validated

    Returns:
        Formatted error response with details about each validation failure
    """
    # Extract missing fields
    missing_fields = [
        str(e["loc"][0]) for e in errors if e["type"] == "missing" and e.get("loc")
    ]

    # Build helpful message
    if missing_fields:
        message = f"Missing required field(s): {', '.join(missing_fields)}"
        recovery = f"Provide the required field(s): {', '.join(missing_fields)}"
    else:
        message = "Input validation failed"
        recovery = "Check the input parameters match the expected schema"

    details: Dict[str, Any] = {"validation_errors": errors}
    if context:
        details["context"] = context

    return error_response(
        error_code="VALIDATION_ERROR",
        message=message,
        recovery_strategy=recovery,
        details=details,
    )


class MCPResponseBuilder:
    """Builder for creating MCP responses with consistent formatting.

    Provides a fluent interface for building responses with
    custom recovery strategies and error mappings.

    Example:
        builder = MCPResponseBuilder()
        builder.set_recovery_strategy("INVALID_URL", "Check URL format")

        # In tool handler:
        try:
            result = do_something()
            return builder.success(result)
        except ValidationError as e:
            return builder.from_exception(e)
    """

    def __init__(self):
        """Initialize builder with default recovery strategies."""
        self._recovery_strategies: Dict[str, str] = {
            # Common error codes
            "VALIDATION_ERROR": "Check the input parameters match the expected schema.",
            "NOT_FOUND": "Verify the resource exists and the identifier is correct.",
            "AUTH_REQUIRED": "Provide a valid JWT token in the Authorization header.",
            "AUTH_INVALID": "The token is invalid or expired. Obtain a new token.",
            "PERMISSION_DENIED": "You don't have permission for this resource.",
            "RATE_LIMITED": "Too many requests. Wait before retrying.",
            "INTERNAL_ERROR": "An unexpected error occurred. Try again or contact support.",
        }

    def set_recovery_strategy(self, error_code: str, strategy: str) -> "MCPResponseBuilder":
        """Set a recovery strategy for an error code.

        Args:
            error_code: The error code to map
            strategy: The recovery strategy text

        Returns:
            Self for method chaining
        """
        self._recovery_strategies[error_code] = strategy
        return self

    def set_recovery_strategies(self, strategies: Dict[str, str]) -> "MCPResponseBuilder":
        """Set multiple recovery strategies at once.

        Args:
            strategies: Dict mapping error codes to recovery strategies

        Returns:
            Self for method chaining
        """
        self._recovery_strategies.update(strategies)
        return self

    def get_recovery_strategy(self, error_code: str) -> str:
        """Get recovery strategy for an error code.

        Args:
            error_code: The error code to look up

        Returns:
            Recovery strategy text, or default message if not found
        """
        return self._recovery_strategies.get(
            error_code,
            "Review the error message and try again.",
        )

    def success(self, data: Any, message: Optional[str] = None) -> ToolResponse:
        """Create a success response.

        Args:
            data: Result data
            message: Optional success message

        Returns:
            Success response
        """
        return success_response(data, message)

    def error(
        self,
        error_code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        recovery_strategy: Optional[str] = None,
    ) -> ToolResponse:
        """Create an error response with automatic recovery strategy lookup.

        Args:
            error_code: Machine-readable error code
            message: Human-readable error message
            details: Optional additional context
            recovery_strategy: Override for the default recovery strategy

        Returns:
            Error response
        """
        strategy = recovery_strategy or self.get_recovery_strategy(error_code)
        return error_response(
            error_code=error_code,
            message=message,
            recovery_strategy=strategy,
            details=details,
        )

    def from_exception(
        self,
        exc: Exception,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> ToolResponse:
        """Create an error response from an exception.

        Handles GofrError subclasses specially to extract code, message, details.

        Args:
            exc: The exception to convert
            error_code: Override error code (uses exception's code if GofrError)
            details: Additional details to merge with exception details

        Returns:
            Error response
        """
        # Import here to avoid circular imports
        from gofr_common.exceptions import GofrError

        if isinstance(exc, GofrError):
            code = error_code or exc.code
            message = exc.message
            exc_details = exc.details.copy() if exc.details else {}
            if details:
                exc_details.update(details)
            return self.error(code, message, exc_details if exc_details else None)

        # Generic exception handling
        code = error_code or "INTERNAL_ERROR"
        return self.error(
            error_code=code,
            message=str(exc),
            details=details,
        )

    def validation_error(
        self,
        errors: List[Dict[str, Any]],
        context: Optional[str] = None,
    ) -> ToolResponse:
        """Create a validation error response.

        Args:
            errors: List of validation errors
            context: Optional context about what was being validated

        Returns:
            Validation error response
        """
        return format_validation_error(errors, context)
