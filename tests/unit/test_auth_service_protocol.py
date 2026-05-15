"""Unit tests for AuthService protocol and factory (Phase A.2)."""

from __future__ import annotations

import os
from unittest.mock import patch

from app.auth.auth_service import AuthService, FailClosedAuthService, get_auth_service


class TestAuthServiceProtocol:
    def test_fail_closed_satisfies_protocol(self) -> None:
        svc = FailClosedAuthService()
        assert isinstance(svc, AuthService)

    def test_fail_closed_returns_empty_string(self) -> None:
        svc = FailClosedAuthService()
        assert svc.authorised_activities("any-token") == ""

    def test_fail_closed_returns_empty_for_empty_token(self) -> None:
        svc = FailClosedAuthService()
        assert svc.authorised_activities("") == ""


class TestGetAuthService:
    def test_returns_fail_closed_by_default(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "GOFR_AGENT_AUTH_MODE"}
        with patch.dict(os.environ, env, clear=True):
            svc = get_auth_service()
        assert isinstance(svc, FailClosedAuthService)

    def test_returns_dev_service_in_dev_mode(self) -> None:
        from app.auth._dev_auth_service import DevAuthService

        with patch.dict(os.environ, {"GOFR_AGENT_AUTH_MODE": "dev"}):
            svc = get_auth_service()
        assert isinstance(svc, DevAuthService)

    def test_unknown_auth_mode_fails_closed(self) -> None:
        with patch.dict(os.environ, {"GOFR_AGENT_AUTH_MODE": "magic"}):
            svc = get_auth_service()
        assert isinstance(svc, FailClosedAuthService)
