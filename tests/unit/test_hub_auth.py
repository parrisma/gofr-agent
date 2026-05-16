"""Tests for callback-token resolution into a service principal."""

from __future__ import annotations

from app.config import GofrAgentConfig
from app.hub.auth import resolve_service_principal
from app.services import ServiceConfig
from app.services.registry import ServiceHubCapabilities, ServiceRegistry


def _make_registry() -> ServiceRegistry:
    return ServiceRegistry(GofrAgentConfig())


class TestResolveServicePrincipal:
    def test_returns_none_for_unknown_callback_token(self) -> None:
        registry = _make_registry()
        registry._services["fixtures"] = ServiceConfig(
            name="fixtures",
            url="http://fixtures/mcp",
            hub_callback_token="fixture-token",
        )

        assert resolve_service_principal("unknown-token", registry) is None

    def test_returns_capabilities_for_matching_service(self) -> None:
        registry = _make_registry()
        registry._services["fixtures"] = ServiceConfig(
            name="fixtures",
            url="http://fixtures/mcp",
            hub_callback_token="fixture-token",
        )
        registry.record_hub_capabilities(
            "fixtures",
            ServiceHubCapabilities(
                supports_results_hub=True,
                can_publish_results=True,
                can_consume_results=False,
                result_types=("ohlcv_bars",),
            ),
        )

        principal = resolve_service_principal("fixture-token", registry)

        assert principal is not None
        assert principal.service_name == "fixtures"
        assert principal.result_types == ("ohlcv_bars",)
        assert principal.can_publish is True
        assert principal.can_consume is False

    def test_uses_compare_digest_even_for_mismatched_lengths(self, monkeypatch) -> None:
        registry = _make_registry()
        registry._services["fixtures"] = ServiceConfig(
            name="fixtures",
            url="http://fixtures/mcp",
            hub_callback_token="fixture-token",
        )
        calls: list[tuple[str, str]] = []

        def fake_compare_digest(left: str, right: str) -> bool:
            calls.append((left, right))
            return left == right

        monkeypatch.setattr("app.hub.auth.secrets.compare_digest", fake_compare_digest)

        result = resolve_service_principal("x", registry)

        assert result is None
        assert calls == [("fixture-token", "x")]
