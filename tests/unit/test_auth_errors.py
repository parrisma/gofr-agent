"""Unit tests for the auth exception hierarchy (Phase A.1)."""

from __future__ import annotations

import pytest

from app.exceptions import (
    AuthorizationError,
    AuthServiceError,
    AuthServiceUnavailableError,
    AuthTokenInvalidError,
    GofrAgentError,
)


class TestAuthorizationError:
    def test_is_gofr_agent_error(self) -> None:
        err = AuthorizationError("GoFRAgentPing")
        assert isinstance(err, GofrAgentError)

    def test_message_includes_activity(self) -> None:
        err = AuthorizationError("GoFRAgentAsk")
        assert "GoFRAgentAsk" in str(err)

    def test_required_activity_attribute(self) -> None:
        err = AuthorizationError("GoFRAgentListServices")
        assert err.required_activity == "GoFRAgentListServices"


class TestAuthServiceError:
    def test_is_gofr_agent_error(self) -> None:
        assert issubclass(AuthServiceError, GofrAgentError)

    def test_auth_token_invalid_is_auth_service_error(self) -> None:
        err = AuthTokenInvalidError("bad token")
        assert isinstance(err, AuthServiceError)
        assert isinstance(err, GofrAgentError)

    def test_auth_service_unavailable_is_auth_service_error(self) -> None:
        err = AuthServiceUnavailableError("down")
        assert isinstance(err, AuthServiceError)
        assert isinstance(err, GofrAgentError)

    def test_raises_as_base(self) -> None:
        with pytest.raises(AuthServiceError):
            raise AuthTokenInvalidError("bad")

    def test_raises_as_gofr_error(self) -> None:
        with pytest.raises(GofrAgentError):
            raise AuthServiceUnavailableError("unavailable")
