"""GofrAgentConfig — typed configuration for gofr-agent.

Loaded explicitly from environment variables via ``GofrAgentConfig.from_env()``.
All fields have safe defaults so the server can be started with minimal config.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel


class GofrAgentConfig(BaseModel):
    """Typed configuration for gofr-agent.

    All fields are optional with defaults so that tests can instantiate without
    environment variables.  Authentication is now managed by ``AuthService``
    injection (see ``app.auth.get_auth_service``), not by config flags.
    """

    # Network
    mcp_port: int = 8090
    mcpo_port: int = 8091
    host: str = "0.0.0.0"  # nosec B104 - intentional server bind address

    # LLM
    llm_model: str = "openai:gpt-4o-mini"
    openrouter_api_key: str | None = None

    # Service discovery
    services_file: Path | None = None

    # Agent behaviour
    max_steps: int = 10
    session_ttl_minutes: int = 60
    tool_result_max_chars: int = 4000
    session_pool_size: int = 3

    # Logging
    log_level: str = "INFO"

    @classmethod
    def from_env(
        cls,
        prefix: str = "GOFR_AGENT",
        env: dict[str, str] | None = None,
    ) -> GofrAgentConfig:
        """Build config from environment variables with optional override dict."""
        e = env if env is not None else dict(os.environ)

        def _get(name: str, default: str = "") -> str:
            return e.get(f"{prefix}_{name}", default)

        return cls(
            mcp_port=int(_get("MCP_PORT", "8090")),
            mcpo_port=int(_get("MCPO_PORT", "8091")),
            host=_get("HOST", "0.0.0.0"),  # nosec B104
            llm_model=_get("LLM_MODEL", "openai:gpt-4o-mini"),
            openrouter_api_key=_get("OPENROUTER_API_KEY") or None,
            services_file=Path(_get("SERVICES_FILE")) if _get("SERVICES_FILE") else None,
            max_steps=int(_get("MAX_STEPS", "10")),
            session_ttl_minutes=int(_get("SESSION_TTL_MINUTES", "60")),
            tool_result_max_chars=int(_get("TOOL_RESULT_MAX_CHARS", "4000")),
            session_pool_size=int(_get("SESSION_POOL_SIZE", "3")),
            log_level=_get("LOG_LEVEL", "INFO"),
        )

