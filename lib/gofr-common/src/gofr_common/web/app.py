"""Starlette application factory for GOFR projects.

Provides convenient factory functions for creating Starlette
applications with common middleware and configuration.
"""

from typing import Any, Callable, List, Optional

from gofr_common.web.cors import CORSConfig, create_cors_middleware
from gofr_common.web.middleware import AuthHeaderMiddleware


def create_starlette_app(
    routes: Optional[List[Any]] = None,
    lifespan: Optional[Callable] = None,
    cors_config: Optional[CORSConfig] = None,
    include_auth_middleware: bool = False,
    debug: bool = False,
) -> Any:
    """Create a Starlette application with common GOFR configuration.

    Args:
        routes: List of Route objects
        lifespan: Lifespan context manager for startup/shutdown
        cors_config: CORS configuration (default: permissive)
        include_auth_middleware: Whether to add AuthHeaderMiddleware
        debug: Enable debug mode

    Returns:
        Starlette application with middleware applied

    Example:
        from starlette.routing import Route, Mount
        from gofr_common.web import create_starlette_app, CORSConfig

        async def lifespan(app):
            # Startup
            yield
            # Shutdown

        routes = [
            Mount("/mcp/", app=mcp_handler),
        ]

        app = create_starlette_app(
            routes=routes,
            lifespan=lifespan,
            cors_config=CORSConfig.for_mcp("GOFR_PLOT"),
            include_auth_middleware=True,
        )
    """
    from starlette.applications import Starlette

    # Create base app
    app = Starlette(
        debug=debug,
        routes=routes or [],
        lifespan=lifespan,
    )

    # Add auth header middleware if requested (before CORS)
    if include_auth_middleware:
        app.add_middleware(AuthHeaderMiddleware)  # type: ignore[arg-type]

    # Apply CORS middleware
    if cors_config is None:
        cors_config = CORSConfig.permissive()

    app = create_cors_middleware(app, cors_config)

    return app


def create_mcp_starlette_app(
    mcp_handler: Any,
    lifespan: Optional[Callable] = None,
    env_prefix: Optional[str] = None,
    include_auth_middleware: bool = False,
    mcp_path: str = "/mcp/",
    additional_routes: Optional[List[Any]] = None,
    debug: bool = False,
) -> Any:
    """Create a Starlette application configured for MCP Streamable HTTP.

    This is a specialized factory for MCP servers with common patterns:
    - Mounts MCP handler at /mcp/
    - Configures CORS with Mcp-Session-Id exposed
    - Optional auth header middleware

    Args:
        mcp_handler: The MCP Streamable HTTP handler
        lifespan: Lifespan context manager
        env_prefix: Environment variable prefix for CORS config
        include_auth_middleware: Whether to add AuthHeaderMiddleware
        mcp_path: Path to mount MCP handler (default: "/mcp/")
        additional_routes: Extra routes to include
        debug: Enable debug mode

    Returns:
        Starlette application ready for MCP transport

    Example:
        from gofr_common.web import create_mcp_starlette_app

        app = create_mcp_starlette_app(
            mcp_handler=handle_streamable_http,
            lifespan=lifespan,
            env_prefix="GOFR_PLOT",
            include_auth_middleware=True,
        )

        # Run with uvicorn
        uvicorn.run(app, host="0.0.0.0", port=8001)
    """
    from starlette.routing import Mount

    # Build routes
    routes = [Mount(mcp_path, app=mcp_handler)]

    if additional_routes:
        routes.extend(additional_routes)

    # Configure CORS for MCP
    cors_config = CORSConfig.for_mcp(env_prefix)

    return create_starlette_app(
        routes=routes,
        lifespan=lifespan,
        cors_config=cors_config,
        include_auth_middleware=include_auth_middleware,
        debug=debug,
    )
