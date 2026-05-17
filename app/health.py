"""Health and ping payload helpers for gofr-agent."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from starlette.responses import JSONResponse
from starlette.routing import Route

from app import __version__
from app.agent.agent import GofrAgent
from app.agent.tool_factory import model_visible_tools
from app.config import GofrAgentConfig
from app.logger import get_logger
from app.request_context import request_log_fields
from app.services.registry import ServiceRegistry

SERVICE_NAME = "gofr-agent"
_ERROR_MAX_CHARS = 512

logger = get_logger("gofr-agent.health")


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _bounded(value: str | None, *, max_chars: int = _ERROR_MAX_CHARS) -> str | None:
    if value is None:
        return None
    cleaned = "".join(char for char in str(value).strip() if char.isprintable())
    if not cleaned:
        return None
    return cleaned[:max_chars]


def build_ping_payload() -> dict[str, str]:
    """Return the common lightweight ping response."""
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "timestamp": _timestamp(),
        "version": __version__,
    }


def _model_config(config: GofrAgentConfig) -> dict[str, Any]:
    return {
        "selected": config.llm_model,
        "allowed_overrides": list(config.allowed_models),
        "openrouter_api_key_configured": bool(config.openrouter_api_key),
    }


def _limits_config(config: GofrAgentConfig) -> dict[str, int]:
    return {
        "agent_timeout_seconds": config.agent_timeout_seconds,
        "max_steps": config.max_steps,
        "max_steps_hard_cap": config.max_steps_hard_cap,
        "max_question_chars": config.max_question_chars,
        "max_context_chars": config.max_context_chars,
        "max_event_payload_chars": config.max_event_payload_chars,
        "max_response_steps": config.max_response_steps,
        "tool_result_max_chars": config.tool_result_max_chars,
        "tool_retry_attempts": config.tool_retry_attempts,
    }


def _session_config(config: GofrAgentConfig) -> dict[str, int]:
    return {
        "session_ttl_minutes": config.session_ttl_minutes,
        "max_sessions": config.max_sessions,
        "max_messages_per_session": config.max_messages_per_session,
        "sweep_interval_seconds": config.session_sweep_interval_seconds,
    }


def _feature_flags(config: GofrAgentConfig) -> dict[str, bool]:
    return {
        "hub_enabled": config.hub_enabled,
        "dynamic_registration_enabled": config.dynamic_registration_enabled,
        "prompt_hardening_v2_enabled": config.prompt_hardening_v2_enabled,
        "caller_content_structured_enabled": config.caller_content_structured_enabled,
        "intent_constraints_enabled": config.intent_constraints_enabled,
        "grounding_enforcement_enabled": config.grounding_enforcement_enabled,
        "verification_gap_response_enabled": config.verification_gap_response_enabled,
        "provenance_in_response_enabled": config.provenance_in_response_enabled,
        "interactive_default": config.interactive_default,
        "allow_unauthenticated_resume": config.allow_unauthenticated_resume,
    }


def _hub_config(config: GofrAgentConfig) -> dict[str, Any]:
    return {
        "enabled": config.hub_enabled,
        "hub_url_configured": bool(config.hub_url),
        "protocol_version": config.hub_protocol_version,
        "default_ttl_seconds": config.hub_default_ttl_seconds,
        "max_payload_bytes": config.hub_max_payload_bytes,
        "max_results": config.hub_max_results,
    }


def _config_payload(config: GofrAgentConfig) -> dict[str, Any]:
    return {
        "models": _model_config(config),
        "limits": _limits_config(config),
        "sessions": _session_config(config),
        "features": _feature_flags(config),
        "hub": _hub_config(config),
    }


def _effective_service_status(status: str, registration_error: str | None) -> str:
    if status == "failed":
        return "failed"
    if status == "healthy" and registration_error is None:
        return "healthy"
    return "degraded"


def _downstream_summary(registry: ServiceRegistry) -> dict[str, Any]:
    visible_tools = model_visible_tools(registry.all_tools)
    items: list[dict[str, Any]] = []

    for service in registry.all_service_configs:
        name = service.name
        capabilities = registry.service_hub_capabilities(name)
        registration_error = _bounded(capabilities.registration_error)
        status = _effective_service_status(registry.service_status(name), registration_error)
        item: dict[str, Any] = {
            "name": name,
            "status": status,
            "tool_count": sum(1 for tool in visible_tools if tool.service_name == name),
            "supports_results_hub": capabilities.supports_results_hub,
            "can_publish_results": capabilities.can_publish_results,
            "can_consume_results": capabilities.can_consume_results,
            "result_types": list(capabilities.result_types),
        }
        error = _bounded(registry.service_error(name))
        if error is not None:
            item["error"] = error
        if registration_error is not None:
            item["registration_error"] = registration_error
        items.append(item)

    healthy = sum(1 for item in items if item["status"] == "healthy")
    degraded = sum(1 for item in items if item["status"] == "degraded")
    failed = sum(1 for item in items if item["status"] == "failed")
    return {
        "total": len(items),
        "healthy": healthy,
        "degraded": degraded,
        "failed": failed,
        "items": items,
    }


def _overall_status(agent: GofrAgent, downstream: dict[str, Any]) -> tuple[str, str]:
    if not bool(getattr(agent, "is_built", True)):
        return "unhealthy", "Agent has not been built"
    if downstream["total"] == 0:
        return "healthy", "No downstream services registered"
    if downstream["degraded"] or downstream["failed"]:
        return "degraded", "One or more downstream services are degraded or failed"
    return "healthy", "All registered services are healthy"


def build_health_payload(
    config: GofrAgentConfig,
    registry: ServiceRegistry,
    agent: GofrAgent,
) -> dict[str, Any]:
    """Return authenticated health diagnostics without secret-bearing fields."""
    downstream = _downstream_summary(registry)
    status, message = _overall_status(agent, downstream)
    return {
        "status": status,
        "message": message,
        "service": SERVICE_NAME,
        "timestamp": _timestamp(),
        "version": __version__,
        "config": _config_payload(config),
        "downstream_services": downstream,
    }


def build_http_health_payload(
    config: GofrAgentConfig,
    registry: ServiceRegistry,
    agent: GofrAgent,
) -> dict[str, Any]:
    """Return the compact unauthenticated HTTP health payload."""
    detailed = build_health_payload(config, registry, agent)
    downstream = detailed["downstream_services"]
    return {
        "status": detailed["status"],
        "service": detailed["service"],
        "timestamp": detailed["timestamp"],
        "version": detailed["version"],
        "message": detailed["message"],
        "downstream": {
            "total": downstream["total"],
            "healthy": downstream["healthy"],
            "degraded": downstream["degraded"],
            "failed": downstream["failed"],
        },
    }


def _unhealthy_http_payload() -> dict[str, Any]:
    return {
        "status": "unhealthy",
        "service": SERVICE_NAME,
        "timestamp": _timestamp(),
        "version": __version__,
        "message": "Health check unavailable",
        "downstream": {"total": 0, "healthy": 0, "degraded": 0, "failed": 0},
    }


def create_health_routes(
    config: GofrAgentConfig,
    registry: ServiceRegistry,
    agent: GofrAgent,
) -> list[Route]:
    """Create unauthenticated Starlette routes for `/ping` and `/health`."""

    async def ping(_request: object) -> JSONResponse:
        return JSONResponse(build_ping_payload())

    async def health(_request: object) -> JSONResponse:
        try:
            payload = build_http_health_payload(config, registry, agent)
        except Exception as exc:
            logger.error(
                "HTTP health payload construction failed",
                error_class=type(exc).__name__,
                **request_log_fields(),
            )
            payload = _unhealthy_http_payload()
        status_code = 503 if payload["status"] == "unhealthy" else 200
        return JSONResponse(payload, status_code=status_code)

    return [
        Route("/ping", endpoint=ping, methods=["GET"]),
        Route("/health", endpoint=health, methods=["GET"]),
    ]
