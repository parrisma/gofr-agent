"""Test-only AuthService implementation with a fixed token map.

Mirrors the structure of DevAuthService but lives in the test tree so
production code never depends on it.
"""

from __future__ import annotations

from app.auth.permissions import (
    AGENT_ASK,
    AGENT_LIST_SERVICES,
    AGENT_MODEL_OVERRIDE,
    AGENT_PING,
    AGENT_REFRESH_SERVICES,
    AGENT_REGISTER_SERVICE,
    AGENT_RESET_SESSION,
)

_ALL = ",".join([
    AGENT_PING,
    AGENT_LIST_SERVICES,
    AGENT_ASK,
    AGENT_MODEL_OVERRIDE,
    AGENT_RESET_SESSION,
    AGENT_REGISTER_SERVICE,
    AGENT_REFRESH_SERVICES,
    "MCPServer*",
])

_READ_ONLY = ",".join([AGENT_PING, AGENT_LIST_SERVICES, AGENT_ASK])

_TOKEN_MAP: dict[str, str] = {
    "dev-admin-token": _ALL,
    "dev-read-token": _READ_ONLY,
}


class DummyAuthService:
    """Deterministic AuthService for unit tests."""

    def authorised_activities(self, token: str) -> str:
        return _TOKEN_MAP.get(token, "")
