"""Unit tests for activity constants and permission helpers (Phase A.4)."""

from __future__ import annotations

import pytest

from app.auth._dev_auth_service import DevAuthService
from app.auth.auth_service import FailClosedAuthService
from app.auth.permissions import (
    AGENT_ASK,
    AGENT_HUB_FETCH,
    AGENT_HUB_REGISTER,
    AGENT_HUB_STORE,
    AGENT_LIST_SERVICES,
    AGENT_MODEL_OVERRIDE,
    AGENT_PING,
    AGENT_REFRESH_SERVICES,
    AGENT_REGISTER_SERVICE,
    AGENT_RESET_SESSION,
    ALL_ACTIVITIES,
    downstream_activity,
    is_authorised,
    parse_authorised_activities,
    require_activity,
)
from app.exceptions import AuthorizationError
from tests.helpers.dummy_auth_service import DummyAuthService


class TestActivityConstants:
    def test_all_activities_complete(self) -> None:
        expected = {
            AGENT_PING,
            AGENT_LIST_SERVICES,
            AGENT_ASK,
            AGENT_MODEL_OVERRIDE,
            AGENT_RESET_SESSION,
            AGENT_REGISTER_SERVICE,
            AGENT_REFRESH_SERVICES,
            AGENT_HUB_STORE,
            AGENT_HUB_FETCH,
            AGENT_HUB_REGISTER,
        }
        assert set(ALL_ACTIVITIES) == expected

    def test_constant_values(self) -> None:
        assert AGENT_PING == "GoFRAgentPing"
        assert AGENT_LIST_SERVICES == "GoFRAgentListServices"
        assert AGENT_ASK == "GoFRAgentAsk"
        assert AGENT_MODEL_OVERRIDE == "GoFRAgentModelOverride"
        assert AGENT_RESET_SESSION == "GoFRAgentResetSession"
        assert AGENT_REGISTER_SERVICE == "GoFRAgentRegisterService"
        assert AGENT_REFRESH_SERVICES == "GoFRAgentRefreshServices"
        assert AGENT_HUB_STORE == "GoFRAgentHubStore"
        assert AGENT_HUB_FETCH == "GoFRAgentHubFetch"
        assert AGENT_HUB_REGISTER == "GoFRAgentHubRegister"


class TestDevAuthServiceHubTokens:
    def test_existing_tokens_do_not_grant_hub_activities(self) -> None:
        service = DevAuthService()

        assert AGENT_HUB_STORE not in parse_authorised_activities(
            service.authorised_activities("dev-admin-token")
        )
        assert AGENT_HUB_FETCH not in parse_authorised_activities(
            service.authorised_activities("dev-read-token")
        )

    def test_fixture_hub_token_grants_only_hub_store_and_fetch(self) -> None:
        service = DevAuthService()

        activities = parse_authorised_activities(
            service.authorised_activities("dev-fixtures-hub-token")
        )

        assert activities == {AGENT_HUB_STORE, AGENT_HUB_FETCH}


class TestParseAuthorisedActivities:
    def test_empty_string_returns_empty_set(self) -> None:
        assert parse_authorised_activities("") == set()

    def test_single_activity(self) -> None:
        assert parse_authorised_activities("GoFRAgentPing") == {"GoFRAgentPing"}

    def test_multiple_activities(self) -> None:
        raw = "GoFRAgentPing,GoFRAgentAsk"
        result = parse_authorised_activities(raw)
        assert result == {"GoFRAgentPing", "GoFRAgentAsk"}

    def test_strips_whitespace(self) -> None:
        raw = " GoFRAgentPing , GoFRAgentAsk "
        result = parse_authorised_activities(raw)
        assert result == {"GoFRAgentPing", "GoFRAgentAsk"}

    def test_ignores_empty_parts(self) -> None:
        raw = "GoFRAgentPing,,GoFRAgentAsk"
        result = parse_authorised_activities(raw)
        assert result == {"GoFRAgentPing", "GoFRAgentAsk"}


class TestDownstreamActivity:
    def test_basic(self) -> None:
        result = downstream_activity("my-service", "do_work")
        assert result == "MCPServerMyServiceToolDoWork"

    def test_underscores_stripped(self) -> None:
        result = downstream_activity("echo_service", "echo_tool")
        assert result.startswith("MCPServer")


class TestIsAuthorised:
    def test_admin_token_authorised(self) -> None:
        svc = DummyAuthService()
        assert is_authorised(svc, "dev-admin-token", AGENT_PING)

    def test_read_token_authorised_for_ping(self) -> None:
        svc = DummyAuthService()
        assert is_authorised(svc, "dev-read-token", AGENT_PING)

    def test_read_token_not_authorised_for_register(self) -> None:
        svc = DummyAuthService()
        assert not is_authorised(svc, "dev-read-token", AGENT_REGISTER_SERVICE)

    def test_unknown_token_denied(self) -> None:
        svc = DummyAuthService()
        assert not is_authorised(svc, "bad-token", AGENT_PING)

    def test_fail_closed_denies_everything(self) -> None:
        svc = FailClosedAuthService()
        assert not is_authorised(svc, "dev-admin-token", AGENT_PING)

    def test_wildcard_allows_downstream(self) -> None:
        svc = DummyAuthService()
        activity = downstream_activity("my-svc", "my-tool")
        assert is_authorised(svc, "dev-admin-token", activity)

    def test_read_token_denied_downstream(self) -> None:
        svc = DummyAuthService()
        activity = downstream_activity("my-svc", "my-tool")
        assert not is_authorised(svc, "dev-read-token", activity)

    def test_type_error_for_non_auth_service(self) -> None:
        with pytest.raises(TypeError):
            is_authorised(object(), "token", AGENT_PING)


class TestRequireActivity:
    def test_passes_for_authorised_token(self) -> None:
        svc = DummyAuthService()
        require_activity(svc, "dev-admin-token", AGENT_PING)  # no raise

    def test_raises_authorization_error_for_unauthorised(self) -> None:
        svc = DummyAuthService()
        with pytest.raises(AuthorizationError) as exc_info:
            require_activity(svc, "dev-read-token", AGENT_REGISTER_SERVICE)
        assert exc_info.value.required_activity == AGENT_REGISTER_SERVICE

    def test_raises_for_unknown_token(self) -> None:
        svc = DummyAuthService()
        with pytest.raises(AuthorizationError):
            require_activity(svc, "bad-token", AGENT_PING)
