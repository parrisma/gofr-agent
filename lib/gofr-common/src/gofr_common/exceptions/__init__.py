"""Common exceptions for GOFR applications.

All exceptions include structured error information:
- code: Machine-readable error identifier
- message: Human-readable error description
- details: Additional context for debugging/recovery

Usage:
    from gofr_common.exceptions import (
        GofrError,
        ValidationError,
        ResourceNotFoundError,
        SecurityError,
        ConfigurationError,
        RegistryError,
    )

Projects can create aliases for backward compatibility:
    GofrDocError = GofrError  # Alias for project-specific naming
"""

from gofr_common.exceptions.base import (
    ConfigurationError,
    GofrError,
    RegistryError,
    ResourceNotFoundError,
    SecurityError,
    ValidationError,
)

__all__ = [
    # Base exceptions
    "GofrError",
    "ValidationError",
    "ResourceNotFoundError",
    "SecurityError",
    "ConfigurationError",
    "RegistryError",
]
