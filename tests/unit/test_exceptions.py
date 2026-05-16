"""Tests for app.exceptions hierarchy."""

import pytest

from app.exceptions import (
    ConfigurationError,
    GofrAgentError,
    ServiceConnectionError,
    ServiceRegistrationPolicyError,
    SessionCapacityError,
    SessionNotFoundError,
    ToolDiscoveryError,
    ToolResultTruncatedWarning,
)


class TestExceptionHierarchy:
    def test_base_is_exception(self) -> None:
        assert issubclass(GofrAgentError, Exception)

    def test_service_connection_error_is_base(self) -> None:
        assert issubclass(ServiceConnectionError, GofrAgentError)

    def test_service_registration_policy_is_base(self) -> None:
        assert issubclass(ServiceRegistrationPolicyError, GofrAgentError)

    def test_tool_discovery_error_is_base(self) -> None:
        assert issubclass(ToolDiscoveryError, GofrAgentError)

    def test_session_not_found_is_base(self) -> None:
        assert issubclass(SessionNotFoundError, GofrAgentError)

    def test_session_capacity_is_base(self) -> None:
        assert issubclass(SessionCapacityError, GofrAgentError)

    def test_truncated_warning_is_base(self) -> None:
        assert issubclass(ToolResultTruncatedWarning, GofrAgentError)

    def test_configuration_error_is_base(self) -> None:
        assert issubclass(ConfigurationError, GofrAgentError)


class TestExceptionInstantiation:
    def test_base_with_message(self) -> None:
        exc = GofrAgentError("boom")
        assert str(exc) == "boom"

    def test_service_connection_with_message(self) -> None:
        exc = ServiceConnectionError("could not connect to http://x")
        assert "http://x" in str(exc)

    def test_service_registration_policy_with_message(self) -> None:
        exc = ServiceRegistrationPolicyError("host blocked")
        assert "host blocked" in str(exc)

    def test_tool_discovery_with_message(self) -> None:
        exc = ToolDiscoveryError("list_tools failed")
        assert str(exc) == "list_tools failed"

    def test_session_not_found_with_message(self) -> None:
        exc = SessionNotFoundError("unknown-session-id")
        assert "unknown-session-id" in str(exc)

    def test_session_capacity_with_message(self) -> None:
        exc = SessionCapacityError("max sessions reached")
        assert "max sessions" in str(exc)

    def test_configuration_error_with_message(self) -> None:
        exc = ConfigurationError("jwt_secret required when require_auth=True")
        assert "jwt_secret" in str(exc)

    def test_can_raise_and_catch_as_base(self) -> None:
        with pytest.raises(GofrAgentError):
            raise ServiceConnectionError("test")

    def test_can_raise_and_catch_as_specific(self) -> None:
        with pytest.raises(ServiceConnectionError):
            raise ServiceConnectionError("test")
