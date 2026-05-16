"""Development-only AuthService backed by a fixed token map.

Never import this module in production code; use ``get_auth_service()`` which
gates it behind GOFR_AGENT_AUTH_MODE=dev.
"""

from __future__ import annotations

from app.auth.permissions import (
    AGENT_ASK,
    AGENT_HUB_FETCH,
    AGENT_HUB_STORE,
    AGENT_LIST_SERVICES,
    AGENT_PING,
    AGENT_REFRESH_SERVICES,
    AGENT_REGISTER_SERVICE,
    AGENT_RESET_SESSION,
)

_ALL = ",".join([
    AGENT_PING,
    AGENT_LIST_SERVICES,
    AGENT_ASK,
    AGENT_RESET_SESSION,
    AGENT_REGISTER_SERVICE,
    AGENT_REFRESH_SERVICES,
    "MCPServer*",
])

_READ_ONLY = ",".join([AGENT_PING, AGENT_LIST_SERVICES, AGENT_ASK])
_HUB_CALLBACK = ",".join([AGENT_HUB_STORE, AGENT_HUB_FETCH])

_TOKEN_MAP: dict[str, str] = {
    "dev-admin-token": _ALL,
    "dev-read-token": _READ_ONLY,
    "dev-fixtures-hub-token": _HUB_CALLBACK,
}


class DevAuthService:
    """Fixed token map for local development and CI."""

    def authorised_activities(self, token: str) -> str:
        return _TOKEN_MAP.get(token, "")
