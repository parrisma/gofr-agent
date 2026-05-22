"""Tests for app.main_mcp wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import GofrAgentConfig
from app.hub import HubStoreHealth
from app.hub.errors import HubError
from app.main_mcp import (
    build_startup_validation_summary,
    create_configured_agent,
    initialise_result_store,
    validate_hub_store_budget,
)
from app.services import ServiceConfig
from app.services.discovery import MCPToolInfo
from app.services.registry import ServiceHubCapabilities, ServiceRegistry
from tests.helpers.dummy_auth_service import DummyAuthService


def test_create_configured_agent_uses_entrypoint_auth_service() -> None:
    config = GofrAgentConfig(llm_model="test")
    registry = MagicMock(spec=ServiceRegistry)
    registry.all_tools = []
    registry.all_service_configs = []
    registry.get_pool = MagicMock(return_value=None)
    auth_service = DummyAuthService()

    agent = create_configured_agent(config, registry, auth_service)

    assert agent.is_built
    assert agent._auth_service is auth_service


def test_build_startup_validation_summary_counts_hub_state() -> None:
    config = GofrAgentConfig(
        llm_model="test",
        hub_enabled=True,
        hub_url="http://gofr-agent:8090/mcp",
    )
    registry = MagicMock(spec=ServiceRegistry)
    registry.all_service_configs = [
        ServiceConfig(name="instruments", url="http://instruments/mcp", hub_callback_token="cb"),
        ServiceConfig(name="analytics", url="http://analytics/mcp", hub_callback_token="cb"),
        ServiceConfig(name="clients", url="http://clients/mcp"),
    ]
    tool_map = {
        "instruments": [
            MCPToolInfo(
                name="_register_results_hub",
                description="",
                input_schema={},
                service_name="instruments",
            )
        ],
        "analytics": [
            MCPToolInfo(
                name="_register_results_hub",
                description="",
                input_schema={},
                service_name="analytics",
            )
        ],
        "clients": [
            MCPToolInfo(
                name="lookup",
                description="",
                input_schema={},
                service_name="clients",
            )
        ],
    }
    caps_map = {
        "instruments": ServiceHubCapabilities(
            supports_results_hub=True,
            can_publish_results=True,
            can_consume_results=True,
        ),
        "analytics": ServiceHubCapabilities(registration_error="hub registration failed"),
        "clients": ServiceHubCapabilities(),
    }
    status_map = {"instruments": "healthy", "analytics": "degraded", "clients": "healthy"}
    registry.service_tools.side_effect = lambda name: list(tool_map[name])
    registry.service_hub_capabilities.side_effect = lambda name: caps_map[name]
    registry.service_status.side_effect = lambda name: status_map[name]

    summary = build_startup_validation_summary(
        config,
        registry,
        HubStoreHealth(
            backend="memory",
            status="healthy",
            reachable=True,
            indexed_result_count=0,
        ),
    )

    assert summary == {
        "hub_enabled": True,
        "hub_url": "http://gofr-agent:8090/mcp",
        "hub_bind_host": "0.0.0.0",
        "hub_bind_port": 8090,
        "hub_url_configured": True,
        "hub_store_backend": "memory",
        "hub_cache_url_configured": False,
        "hub_store_status": "healthy",
        "hub_store_reachable": True,
        "service_count": 3,
        "degraded_service_count": 1,
        "failed_service_count": 0,
        "services_with_hub_callback_token": 2,
        "services_advertising_results_hub": 2,
        "services_supporting_results_hub": 1,
        "services_with_hub_registration_errors": 1,
    }


def test_validate_hub_store_budget_rejects_inconsistent_memory_sizing() -> None:
    config = GofrAgentConfig(
        hub_store_backend="external_cache",
        hub_cache_url="redis://gofr-agent-valkey:6379/0",
        hub_cache_active_session_budget=4,
        hub_max_results=8,
        hub_max_payload_bytes=1024,
        hub_cache_memory_budget_bytes=16_000,
    )

    with pytest.raises(ValueError, match="hub_cache_memory_budget_bytes"):
        validate_hub_store_budget(config)


def test_validate_hub_store_budget_skips_external_cache_budget_check_for_memory_backend() -> None:
    config = GofrAgentConfig(
        hub_store_backend="memory",
        hub_cache_active_session_budget=20,
        hub_max_results=256,
        hub_max_payload_bytes=524_288,
        hub_cache_memory_budget_bytes=268_435_456,
    )

    assert validate_hub_store_budget(config) == 2_684_354_560


@pytest.mark.asyncio
async def test_initialise_result_store_fails_fast_for_unreachable_external_cache() -> None:
    config = GofrAgentConfig(
        hub_enabled=True,
        hub_url="http://gofr-agent:8090/mcp",
        hub_store_backend="external_cache",
        hub_cache_url="redis://gofr-agent-valkey:6379/0",
    )
    store = MagicMock()
    store.start = AsyncMock(
        side_effect=HubError(
            code="hub.store_unavailable",
            message="external cache unavailable during start",
        )
    )
    store.health = AsyncMock()

    with pytest.raises(RuntimeError, match="Hub store startup failed"):
        await initialise_result_store(config, store)
