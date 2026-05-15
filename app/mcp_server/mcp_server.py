"""gofr-agent MCP server definition.

Exposes the following tools via FastMCP:

- ``ping`` — health check
- ``list_services`` — enumerate registered downstream services
- ``ask`` — query the reasoning agent
- ``reset_session`` — clear conversation history for a session
- ``register_service`` — dynamically add a new downstream service
- ``refresh_services`` — re-discover tools for all registered services
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from gofr_common.web import get_auth_header_from_context
from mcp import McpError
from mcp.server.fastmcp import FastMCP
from mcp.types import INVALID_PARAMS, ErrorData

from app import __version__
from app.agent.agent import GofrAgent
from app.auth import (
    AGENT_ASK,
    AGENT_LIST_SERVICES,
    AGENT_PING,
    AGENT_REFRESH_SERVICES,
    AGENT_REGISTER_SERVICE,
    AGENT_RESET_SESSION,
    AuthService,
    extract_bearer_token,
    require_activity,
)
from app.config import GofrAgentConfig
from app.exceptions import AuthorizationError, AuthServiceUnavailableError, AuthTokenInvalidError
from app.services import ServiceConfig
from app.services.registry import ServiceRegistry
from app.sessions.store import SessionStore

logger = logging.getLogger(__name__)


def _guard(auth_service: AuthService, required_activity: str) -> str:
    """Extract the bearer token and enforce *required_activity*.

    Returns the raw token string so callers can forward it downstream.
    Raises McpError on any auth failure (missing token, denied, service down).
    """
    raw = get_auth_header_from_context()
    try:
        token = extract_bearer_token({"authorization": raw})
        require_activity(auth_service, token, required_activity)
    except AuthTokenInvalidError as exc:
        raise McpError(ErrorData(code=INVALID_PARAMS, message=str(exc))) from exc
    except AuthorizationError as exc:
        raise McpError(ErrorData(code=INVALID_PARAMS, message=str(exc))) from exc
    except AuthServiceUnavailableError as exc:
        raise McpError(
            ErrorData(code=INVALID_PARAMS, message="Auth service unavailable")
        ) from exc
    return token


def create_mcp_server(
    config: GofrAgentConfig,
    registry: ServiceRegistry,
    agent: GofrAgent,
    session_store: SessionStore,
    auth_service: AuthService,
) -> FastMCP:
    """Build and return the FastMCP application.

    All five dependencies are injected so they can be mocked in tests.
    """
    mcp = FastMCP(
        name="gofr-agent",
        instructions="Reasoning agent that orchestrates downstream MCP services.",
    )

    # ------------------------------------------------------------------
    # ping
    # ------------------------------------------------------------------

    @mcp.tool()
    async def ping() -> dict[str, str]:
        """Return a health-check payload."""
        _guard(auth_service, AGENT_PING)
        return {
            "status": "ok",
            "timestamp": datetime.now(UTC).isoformat(),
            "version": __version__,
        }

    # ------------------------------------------------------------------
    # list_services
    # ------------------------------------------------------------------

    @mcp.tool()
    async def list_services() -> list[dict[str, Any]]:
        """Return metadata for all registered downstream services."""
        _guard(auth_service, AGENT_LIST_SERVICES)
        result: list[dict[str, Any]] = []
        for name, pool in registry.all_pools.items():
            svc_tools = [
                {"name": f"{t.service_name}__{t.name}", "description": t.description}
                for t in registry.all_tools
                if t.service_name == name
            ]
            result.append(
                {
                    "name": name,
                    "status": "healthy" if pool.is_healthy else "degraded",
                    "tools": svc_tools,
                }
            )
        return result

    # ------------------------------------------------------------------
    # ask
    # ------------------------------------------------------------------

    @mcp.tool()
    async def ask(
        question: str,
        session_id: str | None = None,
        context: str | None = None,
        max_steps: int = 10,
    ) -> dict[str, Any]:
        """Query the reasoning agent and return the answer plus metadata."""
        token = _guard(auth_service, AGENT_ASK)
        session = await session_store.get_or_create(session_id)

        result = await agent.run(
            question,
            session,
            context=context,
            max_steps=max_steps,
            token=token,
        )

        return {
            "session_id": session.session_id,
            "answer": result.answer,
            "steps": result.steps,
            "model": result.model,
            "tokens_used": result.tokens_used,
        }

    # ------------------------------------------------------------------
    # reset_session
    # ------------------------------------------------------------------

    @mcp.tool()
    async def reset_session(session_id: str) -> dict[str, str]:
        """Clear the conversation history for *session_id*."""
        _guard(auth_service, AGENT_RESET_SESSION)
        await session_store.clear(session_id)
        return {"status": "ok", "session_id": session_id}

    # ------------------------------------------------------------------
    # register_service
    # ------------------------------------------------------------------

    @mcp.tool()
    async def register_service(
        name: str,
        url: str,
        token: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Dynamically register a new downstream MCP service."""
        _guard(auth_service, AGENT_REGISTER_SERVICE)
        svc = ServiceConfig(
            name=name,
            url=url,
            token=token,
            description=description or "",
        )
        tools = await registry.register_service(svc)
        agent.rebuild()
        return {
            "status": "registered",
            "name": name,
            "tools_discovered": len(tools),
        }

    # ------------------------------------------------------------------
    # refresh_services
    # ------------------------------------------------------------------

    @mcp.tool()
    async def refresh_services() -> dict[str, Any]:
        """Re-discover tools for all currently registered services."""
        _guard(auth_service, AGENT_REFRESH_SERVICES)
        counts: dict[str, int] = {}
        for name, pool in registry.all_pools.items():
            if pool is not None:
                # We can only return current tool counts without original configs.
                counts[name] = len(
                    [t for t in registry.all_tools if t.service_name == name]
                )

        agent.rebuild()
        return {"status": "refreshed", "services": counts}

    return mcp
