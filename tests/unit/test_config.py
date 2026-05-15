"""Tests for gofr-agent port registration in gofr-common and GofrAgentConfig."""

from gofr_common.config import GOFR_AGENT_PORTS
from gofr_common.config.ports import reset_ports_cache

from app.config import GofrAgentConfig


class TestGofrAgentPorts:
    def setup_method(self) -> None:
        reset_ports_cache()

    def test_mcp_port(self) -> None:
        assert GOFR_AGENT_PORTS.mcp == 8090

    def test_mcpo_port(self) -> None:
        assert GOFR_AGENT_PORTS.mcpo == 8091

    def test_web_port(self) -> None:
        assert GOFR_AGENT_PORTS.web == 8092


class TestGofrAgentConfig:
    def test_defaults(self) -> None:
        cfg = GofrAgentConfig()
        assert cfg.mcp_port == 8090
        assert cfg.mcpo_port == 8091
        assert cfg.host == "0.0.0.0"
        assert cfg.llm_model == "openai:gpt-4o-mini"
        assert cfg.max_steps == 10
        assert cfg.session_ttl_minutes == 60
        assert cfg.tool_result_max_chars == 4000
        assert cfg.session_pool_size == 3
        assert cfg.log_level == "INFO"

    def test_from_env_all_vars(self) -> None:
        env = {
            "GOFR_AGENT_MCP_PORT": "9090",
            "GOFR_AGENT_LLM_MODEL": "anthropic:claude-3-haiku",
            "GOFR_AGENT_MAX_STEPS": "5",
            "GOFR_AGENT_SESSION_TTL_MINUTES": "30",
            "GOFR_AGENT_TOOL_RESULT_MAX_CHARS": "2000",
            "GOFR_AGENT_SESSION_POOL_SIZE": "5",
            "GOFR_AGENT_LOG_LEVEL": "DEBUG",
        }
        cfg = GofrAgentConfig.from_env(env=env)
        assert cfg.mcp_port == 9090
        assert cfg.llm_model == "anthropic:claude-3-haiku"
        assert cfg.max_steps == 5
        assert cfg.session_ttl_minutes == 30
        assert cfg.tool_result_max_chars == 2000
        assert cfg.session_pool_size == 5
        assert cfg.log_level == "DEBUG"
