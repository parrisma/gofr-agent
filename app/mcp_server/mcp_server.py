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

from datetime import UTC, datetime
from typing import Any

from gofr_common.web import get_auth_header_from_context
from mcp import McpError
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import INVALID_PARAMS, ErrorData
from pydantic import ValidationError

from app import __version__
from app.agent.agent import GofrAgent
from app.agent.events import EventCollector, EventSink
from app.agent.tool_factory import model_visible_tools
from app.auth import (
    AGENT_ASK,
    AGENT_HUB_FETCH,
    AGENT_HUB_STORE,
    AGENT_LIST_SERVICES,
    AGENT_MODEL_OVERRIDE,
    AGENT_PING,
    AGENT_REFRESH_SERVICES,
    AGENT_REGISTER_SERVICE,
    AGENT_RESET_SESSION,
    AuthService,
    extract_bearer_token,
    require_activity,
)
from app.config import GofrAgentConfig
from app.exceptions import (
    AuthorizationError,
    AuthServiceUnavailableError,
    AuthTokenInvalidError,
    ServiceRegistrationPolicyError,
)
from app.hub import ResultStore
from app.hub.auth import resolve_service_principal
from app.hub.errors import (
    HUB_MALFORMED_REQUEST,
    HUB_REGISTRATION_REQUIRED,
    HUB_RESULT_TYPE_NOT_ALLOWED,
    HUB_UNAUTHORISED,
    HUB_UNREGISTERED_SERVICE,
    HubError,
    hub_mcp_error,
    raise_hub_error,
)
from app.hub.models import (
    DescribeResultRequest,
    DescribeResultResponse,
    GetResultRequest,
    GetResultResponse,
    StoreResultRequest,
    StoreResultResponse,
)
from app.logger import get_logger
from app.request_context import request_log_fields, reset_request_id, set_request_id
from app.services import ServiceConfig
from app.services.registry import ServiceRegistry
from app.sessions.store import SessionStore

logger = get_logger("gofr-agent.mcp")


def _raise_invalid_params(message: str) -> None:
    raise McpError(ErrorData(code=INVALID_PARAMS, message=message))


def _validate_ask_request(
    config: GofrAgentConfig,
    question: str,
    context: str | None,
    max_steps: int | None,
    model_override: str | None,
) -> tuple[str, int, str | None]:
    cleaned_question = question.strip()
    if not cleaned_question:
        _raise_invalid_params("question must not be empty")
    if len(cleaned_question) > config.max_question_chars:
        _raise_invalid_params(
            f"question exceeds max_question_chars ({config.max_question_chars})"
        )
    if context is not None and len(context) > config.max_context_chars:
        _raise_invalid_params(
            f"context exceeds max_context_chars ({config.max_context_chars})"
        )

    resolved_max_steps = config.max_steps if max_steps is None else max_steps
    if resolved_max_steps < 1:
        _raise_invalid_params("max_steps must be at least 1")
    if resolved_max_steps > config.max_steps_hard_cap:
        _raise_invalid_params(
            f"max_steps exceeds max_steps_hard_cap ({config.max_steps_hard_cap})"
        )

    cleaned_model_override = None
    if model_override is not None:
        cleaned_model_override = model_override.strip()
        if not cleaned_model_override:
            _raise_invalid_params("model_override must not be empty when provided")

    return cleaned_question, resolved_max_steps, cleaned_model_override


def _guard(
    auth_service: AuthService,
    required_activity: str,
    *,
    hub_error_code: str | None = None,
) -> str:
    """Extract the bearer token and enforce *required_activity*.

    Returns the raw token string so callers can forward it downstream.
    Raises McpError on any auth failure (missing token, denied, service down).
    """
    raw = get_auth_header_from_context()
    try:
        token = extract_bearer_token({"authorization": raw})
        require_activity(auth_service, token, required_activity)
    except AuthTokenInvalidError as exc:
        if hub_error_code is not None:
            raise hub_mcp_error(hub_error_code, str(exc)) from exc
        logger.warning(
            "Authorisation rejected",
            activity=required_activity,
            outcome="invalid_token",
            error_class=type(exc).__name__,
            **request_log_fields(),
        )
        raise McpError(ErrorData(code=INVALID_PARAMS, message=str(exc))) from exc
    except AuthorizationError as exc:
        if hub_error_code is not None:
            raise hub_mcp_error(hub_error_code, str(exc)) from exc
        logger.warning(
            "Authorisation rejected",
            activity=required_activity,
            outcome="denied",
            error_class=type(exc).__name__,
            **request_log_fields(),
        )
        raise McpError(ErrorData(code=INVALID_PARAMS, message=str(exc))) from exc
    except AuthServiceUnavailableError as exc:
        if hub_error_code is not None:
            raise hub_mcp_error(hub_error_code, "Auth service unavailable") from exc
        logger.error(
            "Authorisation backend unavailable",
            activity=required_activity,
            outcome="unavailable",
            error_class=type(exc).__name__,
            **request_log_fields(),
        )
        raise McpError(
            ErrorData(code=INVALID_PARAMS, message="Auth service unavailable")
        ) from exc
    logger.info(
        "Authorisation granted",
        activity=required_activity,
        outcome="allowed",
        **request_log_fields(),
    )
    return token


def create_mcp_server(
    config: GofrAgentConfig,
    registry: ServiceRegistry,
    agent: GofrAgent,
    session_store: SessionStore,
    auth_service: AuthService,
    result_store: ResultStore | None = None,
) -> FastMCP:
    """Build and return the FastMCP application.

    All five dependencies are injected so they can be mocked in tests.
    """
    mcp = FastMCP(
        name="gofr-agent",
        instructions="Reasoning agent that orchestrates downstream MCP services.",
    )
    store = result_store or ResultStore(config)

    def _require_hub_principal(principal, *, can_publish: bool = False, can_consume: bool = False):
        if principal is None:
            raise_hub_error(
                HUB_UNREGISTERED_SERVICE,
                "Callback token does not map to a registered service",
            )
        if can_publish and not principal.can_publish:
            raise_hub_error(
                HUB_REGISTRATION_REQUIRED,
                "Service is not registered for hub result publishing",
            )
        if can_consume and not principal.can_consume:
            raise_hub_error(
                HUB_REGISTRATION_REQUIRED,
                "Service is not registered for hub result consumption",
            )
        return principal

    def _require_result_type_allowed(principal, result_type: str) -> None:
        if result_type not in principal.result_types:
            raise_hub_error(
                HUB_RESULT_TYPE_NOT_ALLOWED,
                f"result_type is not allowed for service {principal.service_name}: {result_type}",
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
    # _store_result
    # ------------------------------------------------------------------

    @mcp.tool(name="_store_result")
    async def _store_result(
        protocol_version: int,
        producer_service: str,
        producer_tool: str,
        result_type: str,
        schema_id: str,
        payload: Any,
        summary: str | None = None,
        source_args: dict[str, Any] | None = None,
        ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        token = _guard(auth_service, AGENT_HUB_STORE, hub_error_code=HUB_UNAUTHORISED)
        principal = resolve_service_principal(token, registry)
        try:
            request = StoreResultRequest(
                protocol_version=protocol_version,
                producer_service=producer_service,
                producer_tool=producer_tool,
                result_type=result_type,
                schema_id=schema_id,
                payload=payload,
                summary=summary,
                source_args=source_args,
                ttl_seconds=ttl_seconds,
            )
            principal = _require_hub_principal(principal, can_publish=True)
            if principal.service_name != request.producer_service:
                raise_hub_error(
                    HUB_UNREGISTERED_SERVICE,
                    "producer_service does not match callback token",
                )
            _require_result_type_allowed(principal, request.result_type)
            descriptor = await store.store(request)
        except ValidationError as exc:
            raise hub_mcp_error(HUB_MALFORMED_REQUEST, str(exc)) from exc
        except HubError as exc:
            raise hub_mcp_error(exc.code, exc.message) from exc

        return StoreResultResponse(descriptor=descriptor).model_dump()

    # ------------------------------------------------------------------
    # _get_result
    # ------------------------------------------------------------------

    @mcp.tool(name="_get_result")
    async def _get_result(
        protocol_version: int,
        result_guid: str,
        hub_service: str,
        expected_result_type: str | None = None,
        expected_schema_id: str | None = None,
    ) -> dict[str, Any]:
        token = _guard(auth_service, AGENT_HUB_FETCH, hub_error_code=HUB_UNAUTHORISED)
        principal = resolve_service_principal(token, registry)
        try:
            request = GetResultRequest(
                protocol_version=protocol_version,
                result_guid=result_guid,
                hub_service=hub_service,
                expected_result_type=expected_result_type,
                expected_schema_id=expected_schema_id,
            )
            principal = _require_hub_principal(principal, can_consume=True)
            if request.expected_result_type is not None:
                _require_result_type_allowed(principal, request.expected_result_type)
            response = await store.get(request)
            _require_result_type_allowed(principal, response.metadata.result_type)
        except ValidationError as exc:
            raise hub_mcp_error(HUB_MALFORMED_REQUEST, str(exc)) from exc
        except HubError as exc:
            raise hub_mcp_error(exc.code, exc.message) from exc

        return GetResultResponse(**response.model_dump()).model_dump()

    # ------------------------------------------------------------------
    # _describe_result
    # ------------------------------------------------------------------

    @mcp.tool(name="_describe_result")
    async def _describe_result(
        protocol_version: int,
        result_guid: str,
        hub_service: str,
        expected_result_type: str | None = None,
        expected_schema_id: str | None = None,
    ) -> dict[str, Any]:
        token = _guard(auth_service, AGENT_HUB_FETCH, hub_error_code=HUB_UNAUTHORISED)
        principal = resolve_service_principal(token, registry)
        try:
            request = DescribeResultRequest(
                protocol_version=protocol_version,
                result_guid=result_guid,
                hub_service=hub_service,
                expected_result_type=expected_result_type,
                expected_schema_id=expected_schema_id,
            )
            principal = _require_hub_principal(principal, can_consume=True)
            if request.expected_result_type is not None:
                _require_result_type_allowed(principal, request.expected_result_type)
            response = await store.describe(request)
            _require_result_type_allowed(principal, response.metadata.result_type)
        except ValidationError as exc:
            raise hub_mcp_error(HUB_MALFORMED_REQUEST, str(exc)) from exc
        except HubError as exc:
            raise hub_mcp_error(exc.code, exc.message) from exc

        return DescribeResultResponse(**response.model_dump()).model_dump()

    # ------------------------------------------------------------------
    # list_services
    # ------------------------------------------------------------------

    @mcp.tool()
    async def list_services() -> list[dict[str, Any]]:
        """Return metadata for all registered downstream services."""
        _guard(auth_service, AGENT_LIST_SERVICES)
        result: list[dict[str, Any]] = []
        visible_tools = model_visible_tools(registry.all_tools)
        for service in registry.all_service_configs:
            name = service.name
            capabilities = registry.service_hub_capabilities(name)
            svc_tools = [
                {"name": f"{t.service_name}__{t.name}", "description": t.description}
                for t in visible_tools
                if t.service_name == name
            ]
            payload = service.safe_dump()
            payload["status"] = registry.service_status(name)
            payload["tools"] = svc_tools
            payload["supports_results_hub"] = capabilities.supports_results_hub
            payload["can_publish_results"] = capabilities.can_publish_results
            payload["can_consume_results"] = capabilities.can_consume_results
            payload["result_types"] = list(capabilities.result_types)
            error = registry.service_error(name)
            if error is not None:
                payload["error"] = error
            if capabilities.registration_error is not None:
                payload["registration_error"] = capabilities.registration_error
            result.append(payload)
        return result

    # ------------------------------------------------------------------
    # ask
    # ------------------------------------------------------------------

    @mcp.tool()
    async def ask(
        question: str,
        session_id: str | None = None,
        context: str | None = None,
        max_steps: int | None = None,
        model_override: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Query the reasoning agent and return the answer plus metadata."""
        upstream_request_id = str(ctx.request_id) if ctx is not None else None
        request_token, request_id = set_request_id(upstream_request_id)
        try:
            token = _guard(auth_service, AGENT_ASK)
            question, max_steps, model_override = _validate_ask_request(
                config,
                question,
                context,
                max_steps,
                model_override,
            )
            if model_override is not None:
                _guard(auth_service, AGENT_MODEL_OVERRIDE)
                if model_override not in config.allowed_models:
                    _raise_invalid_params("model_override is not in allowed_models")

            session = await session_store.get_or_create(session_id)
            notifier = None
            if ctx is not None:

                async def _notify(payload: dict[str, Any]) -> None:
                    await ctx.request_context.session.send_log_message(
                        level="info",
                        data=payload,
                        logger="gofr-agent.reasoning",
                        related_request_id=ctx.request_id,
                    )

                notifier = _notify

            event_sink = EventSink(
                EventCollector(
                    request_id,
                    session.session_id,
                    max_payload_chars=config.max_event_payload_chars,
                    max_response_steps=config.max_response_steps,
                ),
                notifier=notifier,
            )
            logger.info(
                "ask request started",
                session_id=session.session_id,
                max_steps=max_steps,
                model_override=model_override,
                **request_log_fields(),
            )

            result = await agent.run(
                question,
                session,
                context=context,
                max_steps=max_steps,
                model_override=model_override,
                event_sink=event_sink,
                token=token,
            )

            logger.info(
                "ask request completed",
                session_id=session.session_id,
                tokens_used=result.tokens_used,
                step_count=len(result.steps),
                **request_log_fields(),
            )

            return {
                "session_id": session.session_id,
                "request_id": request_id,
                "answer": result.answer,
                "steps": result.steps,
                "model": result.model,
                "tokens_used": result.tokens_used,
            }
        finally:
            reset_request_id(request_token)

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
        if not config.dynamic_registration_enabled:
            _raise_invalid_params("dynamic registration is disabled")
        svc = ServiceConfig(
            name=name,
            url=url,
            token=token,
            description=description or "",
        )
        tools: list[Any] = []
        try:
            tools = await registry.register_service(svc)
        except ServiceRegistrationPolicyError as exc:
            _raise_invalid_params(str(exc))
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
