"""CORS configuration utilities for GOFR projects.

Provides common CORS configuration patterns that work with both
Starlette applications and FastAPI applications.
"""

import os
from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class CORSConfig:
    """Configuration for CORS middleware.

    Attributes:
        allow_origins: List of allowed origins or ["*"] for all
        allow_methods: List of allowed HTTP methods
        allow_headers: List of allowed headers or ["*"] for all
        allow_credentials: Whether to allow credentials (cookies, auth headers)
        expose_headers: Headers to expose to the client
        max_age: Max age for preflight cache (seconds)
    """
    allow_origins: List[str] = field(default_factory=lambda: ["*"])
    allow_methods: List[str] = field(
        default_factory=lambda: ["GET", "POST", "DELETE", "OPTIONS"]
    )
    allow_headers: List[str] = field(default_factory=lambda: ["*"])
    allow_credentials: bool = True
    expose_headers: List[str] = field(default_factory=list)
    max_age: int = 600

    @classmethod
    def from_env(
        cls,
        env_prefix: str,
        default_origins: Optional[str] = None,
    ) -> "CORSConfig":
        """Create CORSConfig from environment variables.

        Looks for:
        - {env_prefix}_CORS_ORIGINS: Comma-separated origins or "*"
        - {env_prefix}_CORS_CREDENTIALS: "true" or "false"

        Args:
            env_prefix: Environment variable prefix (e.g., "GOFR_PLOT")
            default_origins: Default origins if env var not set
                            (default: "http://localhost:3000,http://localhost:8000")

        Returns:
            CORSConfig instance

        Example:
            # With GOFR_PLOT_CORS_ORIGINS="*"
            config = CORSConfig.from_env("GOFR_PLOT")
            # config.allow_origins == ["*"]

            # With GOFR_DIG_CORS_ORIGINS="https://example.com,https://app.example.com"
            config = CORSConfig.from_env("GOFR_DIG")
            # config.allow_origins == ["https://example.com", "https://app.example.com"]
        """
        if default_origins is None:
            default_origins = "http://localhost:3000,http://localhost:8000"

        origins_str = os.getenv(f"{env_prefix}_CORS_ORIGINS", default_origins)
        origins = get_cors_origins(origins_str)

        credentials_str = os.getenv(f"{env_prefix}_CORS_CREDENTIALS", "true")
        credentials = credentials_str.lower() == "true"

        return cls(
            allow_origins=origins,
            allow_credentials=credentials,
        )

    @classmethod
    def permissive(cls) -> "CORSConfig":
        """Create permissive CORS config allowing all origins.

        Useful for development or internal APIs.

        Returns:
            CORSConfig with allow_origins=["*"]
        """
        return cls(allow_origins=["*"])

    @classmethod
    def for_mcp(cls, env_prefix: Optional[str] = None) -> "CORSConfig":
        """Create CORS config optimized for MCP Streamable HTTP.

        Includes Mcp-Session-Id in exposed headers.

        Args:
            env_prefix: Optional environment prefix for origins

        Returns:
            CORSConfig for MCP transport
        """
        if env_prefix:
            config = cls.from_env(env_prefix)
        else:
            config = cls.permissive()

        config.expose_headers = ["Mcp-Session-Id"]
        config.allow_methods = ["GET", "POST", "DELETE"]
        return config


def get_cors_origins(origins_str: str) -> List[str]:
    """Parse CORS origins from a string.

    Args:
        origins_str: Comma-separated origins or "*" for all

    Returns:
        List of origin strings

    Example:
        >>> get_cors_origins("*")
        ["*"]
        >>> get_cors_origins("https://example.com, https://app.example.com")
        ["https://example.com", "https://app.example.com"]
    """
    if origins_str == "*":
        return ["*"]
    return [origin.strip() for origin in origins_str.split(",") if origin.strip()]


def create_cors_middleware(
    app: Any,
    config: Optional[CORSConfig] = None,
) -> Any:
    """Wrap an ASGI application with CORS middleware.

    Works with both Starlette and FastAPI applications.

    Args:
        app: The ASGI application to wrap
        config: CORS configuration (default: permissive)

    Returns:
        ASGI application wrapped with CORSMiddleware

    Example:
        from starlette.applications import Starlette
        from gofr_common.web import create_cors_middleware, CORSConfig

        app = Starlette(routes=[...])

        # Simple permissive CORS
        app = create_cors_middleware(app)

        # Custom configuration
        config = CORSConfig.from_env("GOFR_PLOT")
        app = create_cors_middleware(app, config)
    """
    from starlette.middleware.cors import CORSMiddleware

    if config is None:
        config = CORSConfig.permissive()

    return CORSMiddleware(
        app,
        allow_origins=config.allow_origins,
        allow_credentials=config.allow_credentials,
        allow_methods=config.allow_methods,
        allow_headers=config.allow_headers,
        expose_headers=config.expose_headers,
        max_age=config.max_age,
    )
