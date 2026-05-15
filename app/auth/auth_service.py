"""AuthService protocol and factory."""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable


@runtime_checkable
class AuthService(Protocol):
    def authorised_activities(self, token: str) -> str:
        """Return authorized activities as a comma-separated string.

        Returns an empty string for unknown or unauthorised tokens.
        Raises AuthServiceUnavailableError if the backend cannot respond.
        """
        ...


def get_auth_service() -> AuthService:
    """Return the configured auth service.

    The default factory fails closed (denies everything).
    Set GOFR_AGENT_AUTH_MODE=dev to use fixed development tokens.
    For tests, inject DummyAuthService directly instead of using this factory.
    """
    if os.environ.get("GOFR_AGENT_AUTH_MODE") == "dev":
        from app.auth._dev_auth_service import DevAuthService  # noqa: PLC0415

        return DevAuthService()
    return FailClosedAuthService()


class FailClosedAuthService:
    """Default AuthService implementation: deny every token."""

    def authorised_activities(self, token: str) -> str:
        return ""
