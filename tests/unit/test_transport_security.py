"""Tests for inbound MCP transport-security helpers."""

from __future__ import annotations

from types import SimpleNamespace

from app.config import GofrAgentConfig
from app.transport_security import (
    MCP_REQUEST_HEADERS,
    apply_transport_security,
    build_mcp_cors_config,
    build_transport_security_settings,
)


class TestTransportSecuritySettings:
    def test_build_transport_security_settings_from_config(self) -> None:
        config = GofrAgentConfig(
            mcp_allowed_hosts=["gofr-agent-dev:*", "127.0.0.1:*"],
            mcp_allowed_origins=["http://localhost:3000"],
        )

        settings = build_transport_security_settings(config)

        assert settings.enable_dns_rebinding_protection is True
        assert settings.allowed_hosts == ["gofr-agent-dev:*", "127.0.0.1:*"]
        assert settings.allowed_origins == ["http://localhost:3000"]

    def test_build_transport_security_settings_deduplicates_extras(self) -> None:
        config = GofrAgentConfig(
            mcp_allowed_hosts=["127.0.0.1:*"],
            mcp_allowed_origins=["http://localhost:3000"],
        )

        settings = build_transport_security_settings(
            config,
            extra_allowed_hosts=["127.0.0.1:*", "gofr-agent-dev:*"],
            extra_allowed_origins=["http://localhost:3000", "https://console.example"],
        )

        assert settings.allowed_hosts == ["127.0.0.1:*", "gofr-agent-dev:*"]
        assert settings.allowed_origins == [
            "http://localhost:3000",
            "https://console.example",
        ]

    def test_apply_transport_security_sets_fastmcp_settings(self) -> None:
        mcp = SimpleNamespace(settings=SimpleNamespace())
        config = GofrAgentConfig(mcp_allowed_hosts=["gofr-agent-dev:*"])

        result = apply_transport_security(mcp, config)

        assert result is mcp
        assert mcp.settings.transport_security.allowed_hosts == ["gofr-agent-dev:*"]


class TestMcpCorsConfig:
    def test_empty_cors_origins_disables_cors_middleware(self) -> None:
        assert build_mcp_cors_config(GofrAgentConfig()) is None

    def test_build_mcp_cors_config_uses_explicit_origins(self) -> None:
        config = GofrAgentConfig(cors_allowed_origins=["http://localhost:3000"])

        cors = build_mcp_cors_config(config)

        assert cors is not None
        assert cors.allow_origins == ["http://localhost:3000"]
        assert cors.allow_methods == ["GET", "POST", "DELETE"]
        assert cors.allow_headers == MCP_REQUEST_HEADERS
        assert cors.expose_headers == ["Mcp-Session-Id"]
        assert cors.allow_credentials is True
