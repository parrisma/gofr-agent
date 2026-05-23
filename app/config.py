"""GofrAgentConfig — typed configuration for gofr-agent.

Loaded explicitly from environment variables via ``GofrAgentConfig.from_env()``.
All fields have safe defaults so the server can be started with minimal config.
"""

from __future__ import annotations

import os
from ipaddress import ip_address
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

DEFAULT_MCP_ALLOWED_HOSTS = [
    "127.0.0.1",
    "127.0.0.1:*",
    "localhost",
    "localhost:*",
    "[::1]",
    "[::1]:*",
]
DEFAULT_HUB_STORE_BACKEND = "memory"
HubStoreBackend = Literal["memory", "external_cache"]
_HUB_STORE_BACKENDS: tuple[HubStoreBackend, ...] = ("memory", "external_cache")


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

    # Inbound MCP transport security
    mcp_allowed_hosts: list[str] = Field(default_factory=lambda: list(DEFAULT_MCP_ALLOWED_HOSTS))
    mcp_allowed_origins: list[str] = Field(default_factory=list)
    mcp_dns_rebinding_protection_enabled: bool = True
    cors_allowed_origins: list[str] = Field(default_factory=list)

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
    hub_store_backend: HubStoreBackend = DEFAULT_HUB_STORE_BACKEND
    hub_cache_url: str | None = None
    hub_cache_connect_timeout_seconds: float = Field(default=1.0, gt=0)
    hub_cache_operation_timeout_seconds: float = Field(default=2.0, gt=0)
    hub_cache_max_attempts: int = Field(default=2, ge=1)
    hub_cache_retry_backoff_seconds: float = Field(default=0.2, ge=0)
    hub_cache_request_budget_seconds: float = Field(default=5.0, gt=0)
    hub_cache_key_prefix: str = Field(default="gofr-agent:hub", min_length=1)
    hub_cache_memory_budget_bytes: int = Field(default=268435456, ge=1)
    hub_cache_active_session_budget: int = Field(default=20, ge=1)
    hub_callback_token_ttl_seconds: int = Field(default=600, ge=1)
    hub_callback_token_secret: str | None = None
    hub_cache_healthcheck_interval_seconds: int = Field(default=30, ge=1)
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

    @field_validator("mcp_allowed_hosts")
    @classmethod
    def _validate_mcp_allowed_hosts(cls, hosts: list[str]) -> list[str]:
        return [_validate_mcp_host_pattern(host) for host in hosts]

    @field_validator("mcp_allowed_origins", "cors_allowed_origins")
    @classmethod
    def _validate_http_origins(cls, origins: list[str]) -> list[str]:
        return [_validate_http_origin(origin) for origin in origins]

    @field_validator("hub_cache_key_prefix")
    @classmethod
    def _validate_hub_cache_key_prefix(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("hub_cache_key_prefix must not be empty")
        if any(char.isspace() for char in cleaned):
            raise ValueError("hub_cache_key_prefix must not contain whitespace")
        return cleaned

    @model_validator(mode="after")
    def _validate_hub_settings(self) -> GofrAgentConfig:
        if self.hub_store_backend == "external_cache" and not self.hub_cache_url:
            raise ValueError(
                "hub_cache_url must be set when hub_store_backend is external_cache"
            )

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
                raise ValueError("hub_url must not use a loopback host when hub is enabled")
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
            mcp_allowed_hosts=_get_list("MCP_ALLOWED_HOSTS") or list(DEFAULT_MCP_ALLOWED_HOSTS),
            mcp_allowed_origins=_get_list("MCP_ALLOWED_ORIGINS"),
            mcp_dns_rebinding_protection_enabled=_get_bool(
                "MCP_DNS_REBINDING_PROTECTION_ENABLED",
                True,
            ),
            cors_allowed_origins=_get_list("CORS_ORIGINS"),
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
            session_sweep_interval_seconds=int(_get("SESSION_SWEEP_INTERVAL_SECONDS", "60")),
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
            hub_store_backend=_parse_hub_store_backend(
                _get(
                    "HUB_STORE_BACKEND",
                    DEFAULT_HUB_STORE_BACKEND,
                )
            ),
            hub_cache_url=_get("HUB_CACHE_URL") or None,
            hub_cache_connect_timeout_seconds=float(
                _get("HUB_CACHE_CONNECT_TIMEOUT_SECONDS", "1")
            ),
            hub_cache_operation_timeout_seconds=float(
                _get("HUB_CACHE_OPERATION_TIMEOUT_SECONDS", "2")
            ),
            hub_cache_max_attempts=int(_get("HUB_CACHE_MAX_ATTEMPTS", "2")),
            hub_cache_retry_backoff_seconds=float(
                _get("HUB_CACHE_RETRY_BACKOFF_SECONDS", "0.2")
            ),
            hub_cache_request_budget_seconds=float(
                _get("HUB_CACHE_REQUEST_BUDGET_SECONDS", "5")
            ),
            hub_cache_key_prefix=_get("HUB_CACHE_KEY_PREFIX", "gofr-agent:hub"),
            hub_cache_memory_budget_bytes=int(
                _get("HUB_CACHE_MEMORY_BUDGET_BYTES", "268435456")
            ),
            hub_cache_active_session_budget=int(
                _get("HUB_CACHE_ACTIVE_SESSION_BUDGET", "20")
            ),
            hub_callback_token_ttl_seconds=int(
                _get("HUB_CALLBACK_TOKEN_TTL_SECONDS", "600")
            ),
            hub_callback_token_secret=_get("HUB_CALLBACK_TOKEN_SECRET") or None,
            hub_cache_healthcheck_interval_seconds=int(
                _get("HUB_CACHE_HEALTHCHECK_INTERVAL_SECONDS", "30")
            ),
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


def _clean_list_value(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not contain empty values")
    if cleaned != value or any(char.isspace() for char in cleaned):
        raise ValueError(f"{field_name} must not contain whitespace")
    if any(not char.isprintable() for char in cleaned):
        raise ValueError(f"{field_name} must contain printable values")
    return cleaned


def _validate_mcp_host_pattern(value: str) -> str:
    host = _clean_list_value(value, "mcp_allowed_hosts")
    if host == "*":
        raise ValueError("mcp_allowed_hosts must not contain bare wildcard '*'")
    if "://" in host or any(char in host for char in "/?#"):
        raise ValueError("mcp_allowed_hosts entries must be Host header values, not URLs")
    if "*" in host and not host.endswith(":*"):
        raise ValueError("mcp_allowed_hosts only supports wildcard port patterns")
    if host.endswith(":*") and host[:-2] == "":
        raise ValueError("mcp_allowed_hosts wildcard port pattern requires a host")
    return host


def _validate_http_origin(value: str) -> str:
    origin = _clean_list_value(value, "allowed origins")
    if origin == "*":
        raise ValueError("origin allow-lists must not contain bare wildcard '*'")

    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("origin allow-list entries must use http or https")
    if not parsed.hostname:
        raise ValueError("origin allow-list entries must include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("origin allow-list entries must not include credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("origin allow-list entries must not include paths or query strings")
    return origin.rstrip("/")


def _parse_hub_store_backend(value: str) -> HubStoreBackend:
    backend = value.strip()
    if backend not in _HUB_STORE_BACKENDS:
        raise ValueError(
            "hub_store_backend must be one of: " + ", ".join(_HUB_STORE_BACKENDS)
        )
    return cast(HubStoreBackend, backend)
