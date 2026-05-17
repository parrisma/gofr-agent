"""GofrAgentConfig — typed configuration for gofr-agent.

Loaded explicitly from environment variables via ``GofrAgentConfig.from_env()``.
All fields have safe defaults so the server can be started with minimal config.
"""

from __future__ import annotations

import os
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, model_validator


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
    agent_timeout_seconds: int = 120
    max_steps: int = 10
    max_steps_hard_cap: int = 50
    max_question_chars: int = 8000
    max_context_chars: int = 16000
    max_event_payload_chars: int = 4000
    max_response_steps: int = 200
    max_sessions: int = 1000
    max_messages_per_session: int = 100
    session_ttl_minutes: int = 60
    session_sweep_interval_seconds: int = 60
    tool_result_max_chars: int = 4000
    tool_retry_attempts: int = 2
    session_pool_size: int = 3
    interactive_default: bool = False
    pending_prompt_ttl_seconds: int = Field(default=600, ge=1)
    allow_unauthenticated_resume: bool = False
    dynamic_registration_enabled: bool = False
    allowed_service_hosts: list[str] = Field(default_factory=list)
    allowed_models: list[str] = Field(default_factory=list)
    hub_enabled: bool = False
    hub_url: str | None = None
    hub_default_ttl_seconds: int = Field(default=3600, ge=1)
    hub_max_payload_bytes: int = Field(default=524288, ge=1)
    hub_max_results: int = Field(default=256, ge=1)
    hub_protocol_version: int = Field(default=1, ge=1)

    # Prompt hardening rollout flags. Defaults preserve current behaviour.
    prompt_hardening_v2_enabled: bool = False
    caller_content_structured_enabled: bool = False
    intent_constraints_enabled: bool = False
    grounding_enforcement_enabled: bool = False
    verification_gap_response_enabled: bool = False
    provenance_in_response_enabled: bool = False

    # Logging
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _validate_hub_settings(self) -> GofrAgentConfig:
        if not self.hub_enabled:
            return self

        if not self.hub_url:
            raise ValueError("hub_url must be set when hub_enabled is true")

        parsed = urlsplit(self.hub_url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("hub_url must use http or https")
        if not parsed.hostname:
            raise ValueError("hub_url must include a hostname")

        hostname = parsed.hostname.lower()
        if hostname == "localhost":
            raise ValueError("hub_url must not use localhost when hub is enabled")

        try:
            if ip_address(hostname).is_loopback:
                raise ValueError(
                    "hub_url must not use a loopback host when hub is enabled"
                )
        except ValueError as exc:
            if "loopback" in str(exc):
                raise

        return self

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

        def _get_bool(name: str, default: bool) -> bool:
            raw = _get(name)
            if raw == "":
                return default
            return raw.strip().lower() in {"1", "true", "yes", "on"}

        def _get_list(name: str) -> list[str]:
            raw = _get(name)
            if raw == "":
                return []
            return [part.strip() for part in raw.split(",") if part.strip()]

        services_file = _get("SERVICES_FILE")

        return cls(
            mcp_port=int(_get("MCP_PORT", "8090")),
            mcpo_port=int(_get("MCPO_PORT", "8091")),
            host=_get("HOST", "0.0.0.0"),  # nosec B104
            llm_model=_get("LLM_MODEL", "openai:gpt-4o-mini"),
            openrouter_api_key=_get("OPENROUTER_API_KEY") or None,
            services_file=Path(services_file) if services_file else None,
            agent_timeout_seconds=int(_get("AGENT_TIMEOUT_SECONDS", "120")),
            max_steps=int(_get("MAX_STEPS", "10")),
            max_steps_hard_cap=int(_get("MAX_STEPS_HARD_CAP", "50")),
            max_question_chars=int(_get("MAX_QUESTION_CHARS", "8000")),
            max_context_chars=int(_get("MAX_CONTEXT_CHARS", "16000")),
            max_event_payload_chars=int(_get("MAX_EVENT_PAYLOAD_CHARS", "4000")),
            max_response_steps=int(_get("MAX_RESPONSE_STEPS", "200")),
            max_sessions=int(_get("MAX_SESSIONS", "1000")),
            max_messages_per_session=int(_get("MAX_MESSAGES_PER_SESSION", "100")),
            session_ttl_minutes=int(_get("SESSION_TTL_MINUTES", "60")),
            session_sweep_interval_seconds=int(
                _get("SESSION_SWEEP_INTERVAL_SECONDS", "60")
            ),
            tool_result_max_chars=int(_get("TOOL_RESULT_MAX_CHARS", "4000")),
            tool_retry_attempts=int(_get("TOOL_RETRY_ATTEMPTS", "2")),
            session_pool_size=int(_get("SESSION_POOL_SIZE", "3")),
            interactive_default=_get_bool("INTERACTIVE_DEFAULT", False),
            pending_prompt_ttl_seconds=int(_get("PENDING_PROMPT_TTL_SECONDS", "600")),
            allow_unauthenticated_resume=_get_bool(
                "ALLOW_UNAUTHENTICATED_RESUME",
                False,
            ),
            dynamic_registration_enabled=_get_bool(
                "DYNAMIC_REGISTRATION_ENABLED",
                False,
            ),
            allowed_service_hosts=_get_list("ALLOWED_SERVICE_HOSTS"),
            allowed_models=_get_list("ALLOWED_MODELS"),
            hub_enabled=_get_bool("HUB_ENABLED", False),
            hub_url=_get("HUB_URL") or None,
            hub_default_ttl_seconds=int(_get("HUB_DEFAULT_TTL_SECONDS", "3600")),
            hub_max_payload_bytes=int(_get("HUB_MAX_PAYLOAD_BYTES", "524288")),
            hub_max_results=int(_get("HUB_MAX_RESULTS", "256")),
            hub_protocol_version=int(_get("HUB_PROTOCOL_VERSION", "1")),
            prompt_hardening_v2_enabled=_get_bool("PROMPT_HARDENING_V2_ENABLED", False),
            caller_content_structured_enabled=_get_bool(
                "CALLER_CONTENT_STRUCTURED_ENABLED",
                False,
            ),
            intent_constraints_enabled=_get_bool("INTENT_CONSTRAINTS_ENABLED", False),
            grounding_enforcement_enabled=_get_bool("GROUNDING_ENFORCEMENT_ENABLED", False),
            verification_gap_response_enabled=_get_bool(
                "VERIFICATION_GAP_RESPONSE_ENABLED",
                False,
            ),
            provenance_in_response_enabled=_get_bool("PROVENANCE_IN_RESPONSE_ENABLED", False),
            log_level=_get("LOG_LEVEL", "INFO"),
        )

