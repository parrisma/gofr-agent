"""Tests for app.main_mcp wiring."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.config import GofrAgentConfig
from app.main_mcp import create_configured_agent
from app.services.registry import ServiceRegistry
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
