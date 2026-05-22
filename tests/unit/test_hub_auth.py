"""Tests for hub auth helpers and callback-token handling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.config import GofrAgentConfig
from app.hub.auth import (
    HUB_CALLBACK_TOKEN_AUDIENCE,
    HUB_CALLBACK_TOKEN_ISSUER,
    HubCallbackTokenError,
    derive_session_namespace,
    keyed_fingerprint,
    mint_hub_callback_token,
    resolve_service_principal,
    validate_hub_callback_token,
)
from app.services import ServiceConfig
from app.services.registry import ServiceHubCapabilities, ServiceRegistry

_TEST_HUB_SECRET = "secret-key"  # pragma: allowlist secret
_WRONG_TEST_HUB_SECRET = "wrong-secret"  # pragma: allowlist secret


def _now() -> datetime:
    return datetime(2026, 5, 19, 12, 0, 0, tzinfo=UTC)


class TestDeriveSessionNamespace:
    def test_is_deterministic_and_opaque(self) -> None:
        namespace_one = derive_session_namespace(_TEST_HUB_SECRET, "session-123")
        namespace_two = derive_session_namespace(_TEST_HUB_SECRET, "session-123")

        assert namespace_one == namespace_two
        assert namespace_one != "session-123"
        assert len(namespace_one) == 32

    def test_changes_when_secret_changes(self) -> None:
        assert derive_session_namespace("secret-a", "session-123") != derive_session_namespace(
            "secret-b",
            "session-123",
        )

    def test_rejects_empty_inputs(self) -> None:
        with pytest.raises(HubCallbackTokenError, match="secret"):
            derive_session_namespace("", "session-123")
        with pytest.raises(HubCallbackTokenError, match="session_id"):
            derive_session_namespace(_TEST_HUB_SECRET, "")


class TestKeyedFingerprint:
    def test_returns_short_stable_value(self) -> None:
        fingerprint = keyed_fingerprint(_TEST_HUB_SECRET, "result-123")

        assert fingerprint == keyed_fingerprint(_TEST_HUB_SECRET, "result-123")
        assert len(fingerprint) == 12

    def test_missing_value_returns_missing(self) -> None:
        assert keyed_fingerprint(_TEST_HUB_SECRET, "") == "missing"


class TestHubCallbackToken:
    def test_round_trip_validates_claims(self) -> None:
        token = mint_hub_callback_token(
            secret=_TEST_HUB_SECRET,
            service="analytics",
            session_namespace="ns-123",
            allowed_operations=("get", "describe"),
            allowed_result_types=("ohlcv_bars",),
            ttl_seconds=600,
            request_id="req-1",
            run_id="run-1",
            now=_now(),
        )

        claims = validate_hub_callback_token(
            token,
            _TEST_HUB_SECRET,
            now=_now() + timedelta(seconds=1),
            expected_service="analytics",
            required_operation="get",
            required_result_type="ohlcv_bars",
        )

        assert claims.iss == HUB_CALLBACK_TOKEN_ISSUER
        assert claims.aud == HUB_CALLBACK_TOKEN_AUDIENCE
        assert claims.service == "analytics"
        assert claims.session_namespace == "ns-123"
        assert claims.ops == ("get", "describe")
        assert claims.result_types == ("ohlcv_bars",)
        assert claims.request_id == "req-1"
        assert claims.run_id == "run-1"

    def test_rejects_expired_token(self) -> None:
        token = mint_hub_callback_token(
            secret=_TEST_HUB_SECRET,
            service="analytics",
            session_namespace="ns-123",
            allowed_operations=("get",),
            ttl_seconds=60,
            now=_now(),
        )

        with pytest.raises(HubCallbackTokenError, match="expired"):
            validate_hub_callback_token(
                token,
                _TEST_HUB_SECRET,
                now=_now() + timedelta(seconds=61),
            )

    def test_rejects_wrong_service(self) -> None:
        token = mint_hub_callback_token(
            secret=_TEST_HUB_SECRET,
            service="analytics",
            session_namespace="ns-123",
            allowed_operations=("get",),
            ttl_seconds=60,
            now=_now(),
        )

        with pytest.raises(HubCallbackTokenError, match="service"):
            validate_hub_callback_token(
                token,
                _TEST_HUB_SECRET,
                now=_now() + timedelta(seconds=1),
                expected_service="instruments",
            )

    def test_rejects_wrong_operation(self) -> None:
        token = mint_hub_callback_token(
            secret=_TEST_HUB_SECRET,
            service="analytics",
            session_namespace="ns-123",
            allowed_operations=("describe",),
            ttl_seconds=60,
            now=_now(),
        )

        with pytest.raises(HubCallbackTokenError, match="operation"):
            validate_hub_callback_token(
                token,
                _TEST_HUB_SECRET,
                now=_now() + timedelta(seconds=1),
                required_operation="get",
            )

    def test_rejects_wrong_result_type_when_restricted(self) -> None:
        token = mint_hub_callback_token(
            secret=_TEST_HUB_SECRET,
            service="analytics",
            session_namespace="ns-123",
            allowed_operations=("get",),
            allowed_result_types=("ohlcv_bars",),
            ttl_seconds=60,
            now=_now(),
        )

        with pytest.raises(HubCallbackTokenError, match="result type"):
            validate_hub_callback_token(
                token,
                _TEST_HUB_SECRET,
                now=_now() + timedelta(seconds=1),
                required_result_type="positions",
            )

    def test_rejects_malformed_token(self) -> None:
        with pytest.raises(HubCallbackTokenError, match="three parts"):
            validate_hub_callback_token("not-a-token", _TEST_HUB_SECRET, now=_now())

    def test_rejects_invalid_signature(self) -> None:
        token = mint_hub_callback_token(
            secret=_TEST_HUB_SECRET,
            service="analytics",
            session_namespace="ns-123",
            allowed_operations=("get",),
            ttl_seconds=60,
            now=_now(),
        )

        with pytest.raises(HubCallbackTokenError, match="signature"):
            validate_hub_callback_token(
                token,
                _WRONG_TEST_HUB_SECRET,
                now=_now() + timedelta(seconds=1),
            )


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
