"""GOFR Common - Shared infrastructure for GOFR projects.

This package provides common functionality shared across all GOFR projects:
- logger: Flexible logging with session tracking and JSON support
- testing: Code quality testing utilities (ruff, pyright integration)
- auth: JWT authentication services and FastAPI middleware
- config: Configuration management with typed settings
- exceptions: Common exception classes with structured error info
- mcp: MCP response formatting and error handling utilities
"""

__version__ = "1.0.0"

# Re-export commonly used items for convenience
from gofr_common.auth import (
    AuthService,
    TokenInfo,
    get_auth_service,
    init_auth_service,
    optional_verify_token,
    verify_token,
)

try:
    from gofr_common.config import (
        AuthSettings,
        Config,
        LogSettings,
        ServerSettings,
        Settings,
        StorageSettings,
        get_settings,
        reset_settings,
    )
except ImportError:
    # Optional config imports may require extra dependencies (e.g., python-dotenv).
    pass
from gofr_common.exceptions import (
    ConfigurationError,
    GofrError,
    RegistryError,
    ResourceNotFoundError,
    SecurityError,
    ValidationError,
)
from gofr_common.logger import (
    ConsoleLogger,
    DefaultLogger,
    Logger,
    StructuredLogger,
    create_logger,
    get_logger,
)
from gofr_common.security_scan import (
    SecurityScanConfig,
    SecurityScanService,
    TrivyExecutionError,
)

try:
    from gofr_common.mcp import (
        MCPResponseBuilder,
        error_response,
        format_validation_error,
        json_text,
        success_response,
    )
except ImportError:
    pass

try:
    from gofr_common.testing import (
        CheckResult,
        CodeQualityChecker,
    )
except ImportError:
    pass

__all__ = [
    "__version__",
    # Logger
    "Logger",
    "DefaultLogger",
    "ConsoleLogger",
    "StructuredLogger",
    "get_logger",
    "create_logger",
    # Testing
    "CheckResult",
    "CodeQualityChecker",
    # Auth
    "AuthService",
    "TokenInfo",
    "init_auth_service",
    "get_auth_service",
    "verify_token",
    "optional_verify_token",
    # Config
    "Config",
    "Settings",
    "ServerSettings",
    "AuthSettings",
    "StorageSettings",
    "LogSettings",
    "get_settings",
    "reset_settings",
    # Exceptions
    "GofrError",
    "ValidationError",
    "ResourceNotFoundError",
    "SecurityError",
    "ConfigurationError",
    "RegistryError",
    # Security scan
    "SecurityScanConfig",
    "SecurityScanService",
    "TrivyExecutionError",
    # MCP
    "json_text",
    "success_response",
    "error_response",
    "format_validation_error",
    "MCPResponseBuilder",
]
