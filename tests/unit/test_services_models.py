"""Tests for service model token resolution and safe dumping."""

from __future__ import annotations

from app.services import ServiceConfig


class TestServiceConfigHubCallbackTokens:
    def test_hub_callback_token_env_resolves(self, monkeypatch) -> None:
        monkeypatch.setenv("FIXTURE_TOKEN", "fixture-inline")
        monkeypatch.setenv("FIXTURE_HUB_TOKEN", "fixture-hub")

        config = ServiceConfig(
            name="fixtures",
            url="http://fixtures/mcp",
            token_env="FIXTURE_TOKEN",
            hub_callback_token_env="FIXTURE_HUB_TOKEN",
        )

        assert config.token == "fixture-inline"
        assert config.hub_callback_token == "fixture-hub"

    def test_explicit_hub_callback_token_takes_precedence(self, monkeypatch) -> None:
        monkeypatch.setenv("FIXTURE_HUB_TOKEN", "fixture-hub-from-env")

        config = ServiceConfig(
            name="fixtures",
            url="http://fixtures/mcp",
            hub_callback_token="explicit-hub-token",
            hub_callback_token_env="FIXTURE_HUB_TOKEN",
        )

        assert config.hub_callback_token == "explicit-hub-token"

    def test_missing_hub_callback_token_is_allowed(self) -> None:
        config = ServiceConfig(name="fixtures", url="http://fixtures/mcp")

        assert config.hub_callback_token is None
        assert config.hub_callback_token_env is None

    def test_safe_dump_excludes_service_tokens(self) -> None:
        config = ServiceConfig(
            name="fixtures",
            url="http://fixtures/mcp",
            token="service-token",
            token_env="FIXTURE_TOKEN",
            hub_callback_token="hub-token",
            hub_callback_token_env="FIXTURE_HUB_TOKEN",
            description="Fixture service",
        )

        payload = config.safe_dump()

        assert payload == {
            "name": "fixtures",
            "url": "http://fixtures/mcp",
            "token_env": "FIXTURE_TOKEN",
            "hub_callback_token_env": "FIXTURE_HUB_TOKEN",
            "description": "Fixture service",
            "enabled": True,
            "timeout_s": 30.0,
            "pool_size": None,
        }
