"""Test-only AuthService implementation with a fixed token map.

Mirrors the structure of DevAuthService but lives in the test tree so
production code never depends on it.
"""

from __future__ import annotations

from app.auth.permissions import (
    AGENT_ASK,
    AGENT_CANCEL_USER_INPUT,
    AGENT_GET_PENDING_USER_INPUT,
    AGENT_HEALTH_CHECK,
    AGENT_HUB_FETCH,
    AGENT_HUB_STORE,
    AGENT_LIST_SERVICES,
    AGENT_MODEL_OVERRIDE,
    AGENT_PING,
    AGENT_REFRESH_SERVICES,
    AGENT_REGISTER_SERVICE,
    AGENT_RESET_SESSION,
    AGENT_RESPOND_TO_USER_INPUT,
)

_ALL = ",".join([
    AGENT_PING,
    AGENT_HEALTH_CHECK,
    AGENT_LIST_SERVICES,
    AGENT_ASK,
    AGENT_MODEL_OVERRIDE,
    AGENT_RESET_SESSION,
    AGENT_REGISTER_SERVICE,
    AGENT_REFRESH_SERVICES,
    AGENT_RESPOND_TO_USER_INPUT,
    AGENT_GET_PENDING_USER_INPUT,
    AGENT_CANCEL_USER_INPUT,
    "MCPServer*",
])

_READ_ONLY = ",".join([AGENT_PING, AGENT_HEALTH_CHECK, AGENT_LIST_SERVICES, AGENT_ASK])
_HUB_CALLBACK = ",".join([AGENT_HUB_STORE, AGENT_HUB_FETCH])

_TOKEN_MAP: dict[str, str] = {
    "dev-admin-token": _ALL,
    "dev-read-token": _READ_ONLY,
    "dev-fixtures-hub-token": _HUB_CALLBACK,
}


class DummyAuthService:
    """Deterministic AuthService for unit tests."""

    def authorised_activities(self, token: str) -> str:
        return _TOKEN_MAP.get(token, "")
