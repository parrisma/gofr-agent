"""Tests for app.auth public surface (Phase A.7)."""

from __future__ import annotations

from app.auth import (
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
    AuthService,
    FailClosedAuthService,
    downstream_activity,
    extract_bearer_token,
    get_auth_service,
    is_authorised,
    parse_authorised_activities,
    require_activity,
)
from app.auth.auth_service import AuthService as _LocalAuthService


class TestAuthPublicSurface:
    def test_auth_service_is_local_protocol(self) -> None:
        assert AuthService is _LocalAuthService

    def test_fail_closed_is_auth_service(self) -> None:
        assert isinstance(FailClosedAuthService(), AuthService)

    def test_get_auth_service_callable(self) -> None:
        assert callable(get_auth_service)

    def test_constants_importable(self) -> None:
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

    def test_all_activities_list(self) -> None:
        assert len(ALL_ACTIVITIES) == 10

    def test_helpers_callable(self) -> None:
        assert callable(downstream_activity)
        assert callable(extract_bearer_token)
        assert callable(is_authorised)
        assert callable(parse_authorised_activities)
        assert callable(require_activity)

