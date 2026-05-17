"""Inbound MCP transport-security and CORS helpers."""

from __future__ import annotations

from typing import Any

from gofr_common.web import CORSConfig
from mcp.server.transport_security import TransportSecuritySettings

from app.config import GofrAgentConfig

MCP_REQUEST_HEADERS = [
    "Authorization",
    "Content-Type",
    "Accept",
    "Mcp-Session-Id",
    "Mcp-Protocol-Version",
]


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def build_transport_security_settings(
    config: GofrAgentConfig,
    *,
    extra_allowed_hosts: list[str] | None = None,
    extra_allowed_origins: list[str] | None = None,
) -> TransportSecuritySettings:
    """Build FastMCP transport security settings from app config."""
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=config.mcp_dns_rebinding_protection_enabled,
        allowed_hosts=_unique(config.mcp_allowed_hosts + (extra_allowed_hosts or [])),
        allowed_origins=_unique(config.mcp_allowed_origins + (extra_allowed_origins or [])),
    )


def apply_transport_security(
    mcp: Any,
    config: GofrAgentConfig,
    *,
    extra_allowed_hosts: list[str] | None = None,
    extra_allowed_origins: list[str] | None = None,
) -> Any:
    """Apply configured FastMCP transport security before ASGI app creation."""
    mcp.settings.transport_security = build_transport_security_settings(
        config,
        extra_allowed_hosts=extra_allowed_hosts,
        extra_allowed_origins=extra_allowed_origins,
    )
    return mcp


def build_mcp_cors_config(config: GofrAgentConfig) -> CORSConfig | None:
    """Return explicit MCP CORS config, or None when CORS is not configured."""
    if not config.cors_allowed_origins:
        return None

    cors = CORSConfig.for_mcp()
    cors.allow_origins = list(config.cors_allowed_origins)
    cors.allow_headers = list(MCP_REQUEST_HEADERS)
    cors.allow_credentials = True
    return cors
