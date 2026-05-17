"""Auth module for gofr-agent.

Provides the AuthService protocol, factory, helpers, and token extraction
utilities.  All public names are defined locally; gofr-common auth utilities
are no longer re-exported from here.
"""

from __future__ import annotations

from app.auth.auth_service import AuthService, FailClosedAuthService, get_auth_service
from app.auth.permissions import (
    AGENT_ASK,
    AGENT_CANCEL_USER_INPUT,
    AGENT_GET_PENDING_USER_INPUT,
    AGENT_HUB_FETCH,
    AGENT_HUB_REGISTER,
    AGENT_HUB_STORE,
    AGENT_LIST_SERVICES,
    AGENT_MODEL_OVERRIDE,
    AGENT_PING,
    AGENT_REFRESH_SERVICES,
    AGENT_REGISTER_SERVICE,
    AGENT_RESET_SESSION,
    AGENT_RESPOND_TO_USER_INPUT,
    ALL_ACTIVITIES,
    downstream_activity,
    is_authorised,
    parse_authorised_activities,
    require_activity,
)
from app.auth.token import extract_bearer_token

__all__ = [
    # auth_service
    "AuthService",
    "FailClosedAuthService",
    "get_auth_service",
    # permissions
    "AGENT_ASK",
    "AGENT_CANCEL_USER_INPUT",
    "AGENT_GET_PENDING_USER_INPUT",
    "AGENT_HUB_FETCH",
    "AGENT_HUB_REGISTER",
    "AGENT_HUB_STORE",
    "AGENT_LIST_SERVICES",
    "AGENT_MODEL_OVERRIDE",
    "AGENT_PING",
    "AGENT_REFRESH_SERVICES",
    "AGENT_REGISTER_SERVICE",
    "AGENT_RESPOND_TO_USER_INPUT",
    "AGENT_RESET_SESSION",
    "ALL_ACTIVITIES",
    "downstream_activity",
    "is_authorised",
    "parse_authorised_activities",
    "require_activity",
    # token
    "extract_bearer_token",
]

