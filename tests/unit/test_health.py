"""Tests for health and ping payload helpers."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from app.config import GofrAgentConfig
from app.health import build_health_payload, build_http_health_payload, build_ping_payload
from app.services import ServiceConfig
from app.services.discovery import MCPToolInfo
from app.services.registry import ServiceHubCapabilities, ServiceRegistry


class _AgentState:
    def __init__(self, *, is_built: bool = True) -> None:
        self.is_built = is_built


def _tool(service_name: str, name: str, *, model_visible: bool = True) -> MCPToolInfo:
    return MCPToolInfo(
        name=name,
        description=f"{name} tool",
        input_schema={},
        service_name=service_name,
        model_visible=model_visible,
    )


def _registry(
    *,
    services: list[ServiceConfig] | None = None,
    statuses: dict[str, str] | None = None,
    errors: dict[str, str | None] | None = None,
    capabilities: dict[str, ServiceHubCapabilities] | None = None,
    tools: list[MCPToolInfo] | None = None,
) -> MagicMock:
    registry = MagicMock(spec=ServiceRegistry)
    registry.all_service_configs = services or []
    registry.all_tools = tools or []
    registry.service_status = MagicMock(
        side_effect=lambda name: (statuses or {}).get(name, "healthy")
    )
    registry.service_error = MagicMock(side_effect=lambda name: (errors or {}).get(name))
    registry.service_hub_capabilities = MagicMock(
        side_effect=lambda name: (capabilities or {}).get(name, ServiceHubCapabilities())
    )
    return registry


def _assert_no_sentinel_values(payload: dict[str, Any], sentinels: set[str]) -> None:
    rendered = json.dumps(payload, sort_keys=True)
    for sentinel in sentinels:
        assert sentinel not in rendered


class TestPingPayload:
    def test_ping_payload_shape(self) -> None:
        payload = build_ping_payload()

        assert payload["status"] == "ok"
        assert payload["service"] == "gofr-agent"
        assert payload["version"]
        assert payload["timestamp"]


class TestHealthPayload:
    def test_empty_registry_is_healthy(self) -> None:
        payload = build_health_payload(GofrAgentConfig(), _registry(), _AgentState())

        assert payload["status"] == "healthy"
        assert payload["message"] == "No downstream services registered"
        assert payload["downstream_services"]["total"] == 0
        assert payload["downstream_services"]["healthy"] == 0
        assert payload["downstream_services"]["items"] == []

    def test_all_healthy_downstream_services(self) -> None:
        service = ServiceConfig(name="instruments", url="http://instruments:8080/mcp")
        registry = _registry(
            services=[service],
            tools=[
                _tool("instruments", "lookup"),
                _tool("instruments", "_register_results_hub", model_visible=False),
            ],
            capabilities={
                "instruments": ServiceHubCapabilities(
                    supports_results_hub=True,
                    can_publish_results=True,
                    can_consume_results=False,
                    result_types=("ohlcv_bars",),
                )
            },
        )

        payload = build_health_payload(GofrAgentConfig(), registry, _AgentState())
        downstream = payload["downstream_services"]

        assert payload["status"] == "healthy"
        assert downstream["total"] == 1
        assert downstream["healthy"] == 1
        assert downstream["items"][0] == {
            "name": "instruments",
            "status": "healthy",
            "tool_count": 1,
            "supports_results_hub": True,
            "can_publish_results": True,
            "can_consume_results": False,
            "result_types": ["ohlcv_bars"],
        }

    def test_degraded_and_failed_services_degrade_overall_status(self) -> None:
        services = [
            ServiceConfig(name="slow", url="http://slow:8080/mcp"),
            ServiceConfig(name="broken", url="http://broken:8080/mcp"),
        ]
        registry = _registry(
            services=services,
            statuses={"slow": "degraded", "broken": "failed"},
            errors={"broken": "connection failed"},
        )

        payload = build_health_payload(GofrAgentConfig(), registry, _AgentState())
        downstream = payload["downstream_services"]

        assert payload["status"] == "degraded"
        assert downstream["healthy"] == 0
        assert downstream["degraded"] == 1
        assert downstream["failed"] == 1
        assert downstream["items"][1]["error"] == "connection failed"

    def test_service_errors_are_bounded(self) -> None:
        service = ServiceConfig(name="broken", url="http://broken:8080/mcp")
        registry = _registry(
            services=[service],
            statuses={"broken": "failed"},
            errors={"broken": "x" * 800},
        )

        payload = build_health_payload(GofrAgentConfig(), registry, _AgentState())

        assert len(payload["downstream_services"]["items"][0]["error"]) == 512

    def test_hub_registration_error_degrades_service(self) -> None:
        service = ServiceConfig(name="publisher", url="http://publisher:8080/mcp")
        registry = _registry(
            services=[service],
            capabilities={
                "publisher": ServiceHubCapabilities(
                    supports_results_hub=False,
                    registration_error="registration blew up" * 80,
                )
            },
        )

        payload = build_health_payload(GofrAgentConfig(), registry, _AgentState())
        item = payload["downstream_services"]["items"][0]

        assert payload["status"] == "degraded"
        assert payload["downstream_services"]["degraded"] == 1
        assert item["status"] == "degraded"
        assert len(item["registration_error"]) == 512

    def test_config_payload_redacts_secret_values(self) -> None:
        config = GofrAgentConfig(
            llm_model="openai:test-model",
            allowed_models=["openai:override"],
            openrouter_api_key="sk-secret-sentinel",  # pragma: allowlist secret
            hub_enabled=True,
            hub_url="http://gofr-agent:8090/mcp",
        )

        payload = build_health_payload(config, _registry(), _AgentState())

        assert payload["config"]["models"] == {
            "selected": "openai:test-model",
            "allowed_overrides": ["openai:override"],
            "openrouter_api_key_configured": True,
        }
        assert payload["config"]["hub"]["hub_url_configured"] is True
        _assert_no_sentinel_values(payload, {"sk-secret-sentinel", "gofr-agent:8090"})

    def test_unbuilt_agent_is_unhealthy(self) -> None:
        payload = build_health_payload(GofrAgentConfig(), _registry(), _AgentState(is_built=False))

        assert payload["status"] == "unhealthy"
        assert payload["message"] == "Agent has not been built"

    def test_downstream_items_use_explicit_allow_list(self) -> None:
        service = ServiceConfig(
            name="secretive",
            url="http://secretive:8080/mcp",
            token="service-token-sentinel",
            token_env="SERVICE_TOKEN_ENV_SENTINEL",
            hub_callback_token="callback-token-sentinel",
            hub_callback_token_env="CALLBACK_TOKEN_ENV_SENTINEL",
            description="private service description",
        )
        payload = build_health_payload(
            GofrAgentConfig(),
            _registry(services=[service], tools=[_tool("secretive", "lookup")]),
            _AgentState(),
        )
        item = payload["downstream_services"]["items"][0]

        assert set(item) == {
            "name",
            "status",
            "tool_count",
            "supports_results_hub",
            "can_publish_results",
            "can_consume_results",
            "result_types",
        }
        _assert_no_sentinel_values(
            payload,
            {
                "http://secretive:8080/mcp",
                "service-token-sentinel",
                "SERVICE_TOKEN_ENV_SENTINEL",
                "callback-token-sentinel",
                "CALLBACK_TOKEN_ENV_SENTINEL",
                "private service description",
            },
        )

    def test_http_health_payload_is_compact(self) -> None:
        service = ServiceConfig(name="broken", url="http://broken:8080/mcp")
        payload = build_http_health_payload(
            GofrAgentConfig(openrouter_api_key="sk-secret-sentinel"),  # pragma: allowlist secret
            _registry(
                services=[service],
                statuses={"broken": "failed"},
                errors={"broken": "secret-ish failure detail"},
            ),
            _AgentState(),
        )

        assert payload["status"] == "degraded"
        assert payload["downstream"] == {
            "total": 1,
            "healthy": 0,
            "degraded": 0,
            "failed": 1,
        }
        assert "config" not in payload
        assert "downstream_services" not in payload
        _assert_no_sentinel_values(payload, {"sk-secret-sentinel", "secret-ish failure detail"})
