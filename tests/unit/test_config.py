"""Tests for gofr-agent port registration in gofr-common and GofrAgentConfig."""

import pytest
from gofr_common.config import GOFR_AGENT_PORTS, load_ports
from gofr_common.config.ports import reset_ports_cache
from pydantic import ValidationError

from app.config import GofrAgentConfig


class TestGofrAgentPorts:
    def setup_method(self) -> None:
        reset_ports_cache()

    def test_default_ports_without_env_overrides(
        self,
        monkeypatch,
    ) -> None:
        monkeypatch.delenv("GOFR_AGENT_MCP_PORT", raising=False)
        monkeypatch.delenv("GOFR_AGENT_MCPO_PORT", raising=False)
        monkeypatch.delenv("GOFR_AGENT_WEB_PORT", raising=False)
        reset_ports_cache()

        ports = load_ports()["gofr-agent"]
        assert ports.mcp == 8090
        assert ports.mcpo == 8091
        assert ports.web == 8092

    def test_runtime_ports_can_be_overridden(self) -> None:
        ports = load_ports(
            env={
                "GOFR_AGENT_MCP_PORT": "8190",
                "GOFR_AGENT_MCPO_PORT": "8191",
                "GOFR_AGENT_WEB_PORT": "8192",
            }
        )["gofr-agent"]
        assert ports.mcp == 8190
        assert ports.mcpo == 8191
        assert ports.web == 8192

    def test_ambient_constant_reflects_loaded_port_map(self) -> None:
        assert load_ports()["gofr-agent"] == GOFR_AGENT_PORTS


class TestGofrAgentConfig:
    def test_defaults(self) -> None:
        cfg = GofrAgentConfig()
        assert cfg.mcp_port == 8090
        assert cfg.mcpo_port == 8091
        assert cfg.host == "0.0.0.0"
        assert cfg.llm_model == "openai:gpt-4o-mini"
        assert cfg.mcp_allowed_hosts == ["127.0.0.1:*", "localhost:*", "[::1]:*"]
        assert cfg.mcp_allowed_origins == []
        assert cfg.mcp_dns_rebinding_protection_enabled is True
        assert cfg.cors_allowed_origins == []
        assert cfg.agent_timeout_seconds == 120
        assert cfg.max_steps == 10
        assert cfg.max_steps_hard_cap == 50
        assert cfg.max_question_chars == 8000
        assert cfg.max_context_chars == 16000
        assert cfg.max_event_payload_chars == 4000
        assert cfg.max_response_steps == 200
        assert cfg.max_sessions == 1000
        assert cfg.max_messages_per_session == 100
        assert cfg.session_ttl_minutes == 60
        assert cfg.session_sweep_interval_seconds == 60
        assert cfg.tool_result_max_chars == 4000
        assert cfg.tool_retry_attempts == 2
        assert cfg.session_pool_size == 3
        assert cfg.interactive_default is False
        assert cfg.pending_prompt_ttl_seconds == 600
        assert cfg.allow_unauthenticated_resume is False
        assert cfg.dynamic_registration_enabled is False
        assert cfg.allowed_service_hosts == []
        assert cfg.allowed_models == []
        assert cfg.hub_enabled is False
        assert cfg.hub_url is None
        assert cfg.hub_default_ttl_seconds > 0
        assert cfg.hub_max_payload_bytes > 0
        assert cfg.hub_max_results > 0
        assert cfg.hub_protocol_version == 1
        assert cfg.prompt_hardening_v2_enabled is False
        assert cfg.caller_content_structured_enabled is False
        assert cfg.intent_constraints_enabled is False
        assert cfg.grounding_enforcement_enabled is False
        assert cfg.verification_gap_response_enabled is False
        assert cfg.provenance_in_response_enabled is False
        assert cfg.log_level == "INFO"

    def test_from_env_all_vars(self) -> None:
        env = {
            "GOFR_AGENT_MCP_PORT": "9090",
            "GOFR_AGENT_LLM_MODEL": "anthropic:claude-3-haiku",
            "GOFR_AGENT_MCP_ALLOWED_HOSTS": ",".join(
                [
                    "gofr-agent-dev",
                    "gofr-agent-dev:8090",
                    "127.0.0.1:*",
                    "localhost:*",
                    "[::1]:*",
                ]
            ),
            "GOFR_AGENT_MCP_ALLOWED_ORIGINS": "http://localhost:3000,https://console.example.internal",
            "GOFR_AGENT_MCP_DNS_REBINDING_PROTECTION_ENABLED": "false",
            "GOFR_AGENT_CORS_ORIGINS": "http://localhost:3000,https://console.example.internal",
            "GOFR_AGENT_AGENT_TIMEOUT_SECONDS": "45",
            "GOFR_AGENT_MAX_STEPS": "5",
            "GOFR_AGENT_MAX_STEPS_HARD_CAP": "25",
            "GOFR_AGENT_MAX_QUESTION_CHARS": "2000",
            "GOFR_AGENT_MAX_CONTEXT_CHARS": "6000",
            "GOFR_AGENT_MAX_EVENT_PAYLOAD_CHARS": "1500",
            "GOFR_AGENT_MAX_RESPONSE_STEPS": "75",
            "GOFR_AGENT_MAX_SESSIONS": "250",
            "GOFR_AGENT_MAX_MESSAGES_PER_SESSION": "40",
            "GOFR_AGENT_SESSION_TTL_MINUTES": "30",
            "GOFR_AGENT_SESSION_SWEEP_INTERVAL_SECONDS": "15",
            "GOFR_AGENT_TOOL_RESULT_MAX_CHARS": "2000",
            "GOFR_AGENT_TOOL_RETRY_ATTEMPTS": "4",
            "GOFR_AGENT_SESSION_POOL_SIZE": "5",
            "GOFR_AGENT_INTERACTIVE_DEFAULT": "true",
            "GOFR_AGENT_PENDING_PROMPT_TTL_SECONDS": "120",
            "GOFR_AGENT_ALLOW_UNAUTHENTICATED_RESUME": "true",
            "GOFR_AGENT_DYNAMIC_REGISTRATION_ENABLED": "true",
            "GOFR_AGENT_ALLOWED_SERVICE_HOSTS": "gofr-*,example.internal",
            "GOFR_AGENT_ALLOWED_MODELS": "openai:gpt-4o-mini,deepseek/deepseek-v4-pro",
            "GOFR_AGENT_HUB_ENABLED": "true",
            "GOFR_AGENT_HUB_URL": "http://gofr-agent:8090/mcp",
            "GOFR_AGENT_HUB_DEFAULT_TTL_SECONDS": "1800",
            "GOFR_AGENT_HUB_MAX_PAYLOAD_BYTES": "524288",
            "GOFR_AGENT_HUB_MAX_RESULTS": "250",
            "GOFR_AGENT_HUB_PROTOCOL_VERSION": "1",
            "GOFR_AGENT_PROMPT_HARDENING_V2_ENABLED": "true",
            "GOFR_AGENT_CALLER_CONTENT_STRUCTURED_ENABLED": "true",
            "GOFR_AGENT_INTENT_CONSTRAINTS_ENABLED": "true",
            "GOFR_AGENT_GROUNDING_ENFORCEMENT_ENABLED": "true",
            "GOFR_AGENT_VERIFICATION_GAP_RESPONSE_ENABLED": "true",
            "GOFR_AGENT_PROVENANCE_IN_RESPONSE_ENABLED": "true",
            "GOFR_AGENT_LOG_LEVEL": "DEBUG",
        }
        cfg = GofrAgentConfig.from_env(env=env)
        assert cfg.mcp_port == 9090
        assert cfg.llm_model == "anthropic:claude-3-haiku"
        assert cfg.mcp_allowed_hosts == [
            "gofr-agent-dev",
            "gofr-agent-dev:8090",
            "127.0.0.1:*",
            "localhost:*",
            "[::1]:*",
        ]
        assert cfg.mcp_allowed_origins == [
            "http://localhost:3000",
            "https://console.example.internal",
        ]
        assert cfg.mcp_dns_rebinding_protection_enabled is False
        assert cfg.cors_allowed_origins == [
            "http://localhost:3000",
            "https://console.example.internal",
        ]
        assert cfg.agent_timeout_seconds == 45
        assert cfg.max_steps == 5
        assert cfg.max_steps_hard_cap == 25
        assert cfg.max_question_chars == 2000
        assert cfg.max_context_chars == 6000
        assert cfg.max_event_payload_chars == 1500
        assert cfg.max_response_steps == 75
        assert cfg.max_sessions == 250
        assert cfg.max_messages_per_session == 40
        assert cfg.session_ttl_minutes == 30
        assert cfg.session_sweep_interval_seconds == 15
        assert cfg.tool_result_max_chars == 2000
        assert cfg.tool_retry_attempts == 4
        assert cfg.session_pool_size == 5
        assert cfg.interactive_default is True
        assert cfg.pending_prompt_ttl_seconds == 120
        assert cfg.allow_unauthenticated_resume is True
        assert cfg.dynamic_registration_enabled is True
        assert cfg.allowed_service_hosts == ["gofr-*", "example.internal"]
        assert cfg.allowed_models == ["openai:gpt-4o-mini", "deepseek/deepseek-v4-pro"]
        assert cfg.hub_enabled is True
        assert cfg.hub_url == "http://gofr-agent:8090/mcp"
        assert cfg.hub_default_ttl_seconds == 1800
        assert cfg.hub_max_payload_bytes == 524288
        assert cfg.hub_max_results == 250
        assert cfg.hub_protocol_version == 1
        assert cfg.prompt_hardening_v2_enabled is True
        assert cfg.caller_content_structured_enabled is True
        assert cfg.intent_constraints_enabled is True
        assert cfg.grounding_enforcement_enabled is True
        assert cfg.verification_gap_response_enabled is True
        assert cfg.provenance_in_response_enabled is True
        assert cfg.log_level == "DEBUG"

    def test_hub_enabled_requires_hub_url(self) -> None:
        with pytest.raises(ValidationError, match="hub_url"):
            GofrAgentConfig.from_env(env={"GOFR_AGENT_HUB_ENABLED": "true"})

    def test_pending_prompt_ttl_must_be_positive(self) -> None:
        with pytest.raises(ValidationError, match="pending_prompt_ttl_seconds"):
            GofrAgentConfig(pending_prompt_ttl_seconds=0)

    @pytest.mark.parametrize(
        "hub_url",
        [
            "http://localhost:8090/mcp",
            "http://127.0.0.1:8090/mcp",
            "http://[::1]:8090/mcp",
        ],
    )
    def test_hub_url_rejects_loopback_hosts(self, hub_url: str) -> None:
        with pytest.raises(ValidationError, match="hub_url"):
            GofrAgentConfig.from_env(
                env={
                    "GOFR_AGENT_HUB_ENABLED": "true",
                    "GOFR_AGENT_HUB_URL": hub_url,
                }
            )

    def test_hub_url_accepts_docker_service_name(self) -> None:
        cfg = GofrAgentConfig.from_env(
            env={
                "GOFR_AGENT_HUB_ENABLED": "true",
                "GOFR_AGENT_HUB_URL": "http://gofr-agent:8090/mcp",
            }
        )

        assert cfg.hub_url == "http://gofr-agent:8090/mcp"

    def test_hub_url_accepts_https_dns_name(self) -> None:
        cfg = GofrAgentConfig.from_env(
            env={
                "GOFR_AGENT_HUB_ENABLED": "true",
                "GOFR_AGENT_HUB_URL": "https://agent.example.internal/mcp",
            }
        )

        assert cfg.hub_url == "https://agent.example.internal/mcp"

    @pytest.mark.parametrize(
        "host_pattern",
        [
            "*",
            "gofr-*",
            "http://gofr-agent:8090",
            "gofr-agent/mcp",
        ],
    )
    def test_mcp_allowed_hosts_rejects_unsafe_patterns(self, host_pattern: str) -> None:
        with pytest.raises(ValidationError, match="mcp_allowed_hosts"):
            GofrAgentConfig(mcp_allowed_hosts=[host_pattern])

    @pytest.mark.parametrize(
        "origin",
        [
            "*",
            "localhost:3000",
            "ftp://console.example.internal",
            "http://console.example.internal/mcp",
            "http://user:pass@console.example.internal",  # pragma: allowlist secret
        ],
    )
    def test_origin_allow_lists_reject_invalid_origins(self, origin: str) -> None:
        with pytest.raises(ValidationError):
            GofrAgentConfig(mcp_allowed_origins=[origin])

    def test_origin_allow_lists_normalise_trailing_slash(self) -> None:
        cfg = GofrAgentConfig(
            mcp_allowed_origins=["http://localhost:3000/"],
            cors_allowed_origins=["https://console.example.internal/"],
        )

        assert cfg.mcp_allowed_origins == ["http://localhost:3000"]
        assert cfg.cors_allowed_origins == ["https://console.example.internal"]
