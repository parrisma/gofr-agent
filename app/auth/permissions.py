"""Activity name constants and authorisation helpers."""

from __future__ import annotations

from app.exceptions import AuthorizationError

# ---------------------------------------------------------------------------
# Activity constants
# ---------------------------------------------------------------------------

AGENT_PING = "GoFRAgentPing"
AGENT_LIST_SERVICES = "GoFRAgentListServices"
AGENT_ASK = "GoFRAgentAsk"
AGENT_MODEL_OVERRIDE = "GoFRAgentModelOverride"
AGENT_RESET_SESSION = "GoFRAgentResetSession"
AGENT_REGISTER_SERVICE = "GoFRAgentRegisterService"
AGENT_REFRESH_SERVICES = "GoFRAgentRefreshServices"
AGENT_HUB_STORE = "GoFRAgentHubStore"
AGENT_HUB_FETCH = "GoFRAgentHubFetch"
AGENT_HUB_REGISTER = "GoFRAgentHubRegister"

ALL_ACTIVITIES: list[str] = [
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
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_authorised_activities(raw: str) -> set[str]:
    """Split a comma-separated activity string into a set.

    Whitespace is stripped from each token.  Empty strings produce an empty
    set.
    """
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


def _title(name: str) -> str:
    """Title-case a service/tool name for use in activity identifiers."""
    return name.title().replace(" ", "").replace("-", "").replace("_", "")


def downstream_activity(service_name: str, tool_name: str) -> str:
    """Return the activity name required to call *tool_name* on *service_name*.

    Example::

        downstream_activity("my-service", "do_work")
        # → "MCPServerMyserviceTool_doWork"  — not exactly, see _title()
        # Actually → "MCPServerMyserviceToolDoWork"
    """
    return f"MCPServer{_title(service_name)}Tool{_title(tool_name)}"


def is_authorised(auth_service: object, token: str, required_activity: str) -> bool:
    """Return True if *token* grants *required_activity*.

    Also returns True when *required_activity* is covered by a wildcard entry
    ``MCPServer*`` in the authorised set.
    """
    from app.auth.auth_service import AuthService  # noqa: PLC0415

    if not isinstance(auth_service, AuthService):
        raise TypeError(f"Expected AuthService, got {type(auth_service)!r}")
    raw = auth_service.authorised_activities(token)
    activities = parse_authorised_activities(raw)
    if required_activity in activities:
        return True
    # wildcard check for downstream (MCPServer*) activities
    return required_activity.startswith("MCPServer") and "MCPServer*" in activities


def require_activity(auth_service: object, token: str, required_activity: str) -> None:
    """Raise :exc:`AuthorizationError` unless *token* grants *required_activity*."""
    if not is_authorised(auth_service, token, required_activity):
        raise AuthorizationError(required_activity)
