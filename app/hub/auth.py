"""Helpers for resolving callback tokens to registered service principals."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import Field, ValidationError

from app.hub.models import HubModel
from app.logger import get_logger

if TYPE_CHECKING:
    from app.services.registry import ServiceRegistry

logger = get_logger("gofr-agent.hub.auth")
HUB_CALLBACK_TOKEN_ISSUER = "gofr-agent"
HUB_CALLBACK_TOKEN_AUDIENCE = "gofr-agent-hub"
HUB_CALLBACK_TOKEN_TYPE = "GOFR-HUB-1"
GOFR_HUB_URL_HEADER = "X-GOFR-HUB-URL"
GOFR_HUB_CALLBACK_TOKEN_HEADER = "X-GOFR-HUB-CALLBACK-TOKEN"


@dataclass(frozen=True)
class HubCallbackTokenError(ValueError):
    reason: str

    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True)
class ServicePrincipal:
    service_name: str
    result_types: tuple[str, ...] = ()
    can_publish: bool = False
    can_consume: bool = False


class HubCallbackTokenClaims(HubModel):
    """Claims carried by a session-bound hub callback token."""

    iss: Literal["gofr-agent"] = HUB_CALLBACK_TOKEN_ISSUER
    aud: Literal["gofr-agent-hub"] = HUB_CALLBACK_TOKEN_AUDIENCE
    typ: Literal["GOFR-HUB-1"] = HUB_CALLBACK_TOKEN_TYPE
    service: str = Field(min_length=1)
    session_namespace: str = Field(min_length=1)
    ops: tuple[str, ...] = ()
    result_types: tuple[str, ...] = ()
    iat: int = Field(ge=0)
    nbf: int = Field(ge=0)
    exp: int = Field(ge=0)
    jti: str = Field(min_length=1)
    request_id: str | None = None
    run_id: str | None = None


def derive_session_namespace(
    secret: str,
    session_id: str,
    *,
    length: int = 32,
) -> str:
    """Return a keyed, non-reversible namespace derived from *session_id*."""
    if not secret:
        raise HubCallbackTokenError("session namespace secret must not be empty")
    if not session_id:
        raise HubCallbackTokenError("session_id must not be empty")
    digest = hmac.new(
        secret.encode("utf-8"),
        session_id.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _base64url_encode(digest)[:length]


def keyed_fingerprint(secret: str, value: str, *, length: int = 12) -> str:
    """Return a short keyed fingerprint safe for logs and metrics."""
    if not value:
        return "missing"
    return derive_session_namespace(secret, value, length=length)


def mint_hub_callback_token(
    *,
    secret: str,
    service: str,
    session_namespace: str,
    allowed_operations: tuple[str, ...],
    allowed_result_types: tuple[str, ...] = (),
    ttl_seconds: int,
    request_id: str | None = None,
    run_id: str | None = None,
    token_id: str | None = None,
    now: datetime | None = None,
) -> str:
    """Mint a signed session-bound hub callback token."""
    if not secret:
        raise HubCallbackTokenError("hub callback token secret must not be empty")
    if not service:
        raise HubCallbackTokenError("service must not be empty")
    if not session_namespace:
        raise HubCallbackTokenError("session_namespace must not be empty")
    if ttl_seconds <= 0:
        raise HubCallbackTokenError("ttl_seconds must be positive")
    if not allowed_operations:
        raise HubCallbackTokenError("allowed_operations must not be empty")

    issued_at = int((now or datetime.now(UTC)).timestamp())
    claims = HubCallbackTokenClaims(
        service=service,
        session_namespace=session_namespace,
        ops=tuple(allowed_operations),
        result_types=tuple(allowed_result_types),
        iat=issued_at,
        nbf=issued_at,
        exp=issued_at + ttl_seconds,
        jti=token_id or secrets.token_urlsafe(16),
        request_id=request_id,
        run_id=run_id,
    )
    header = {"alg": "HS256", "typ": HUB_CALLBACK_TOKEN_TYPE}
    signing_input = _signing_input(header, claims.model_dump())
    signature = _sign(secret, signing_input)
    return f"{signing_input}.{signature}"


def validate_hub_callback_token(
    token: str,
    secret: str,
    *,
    now: datetime | None = None,
    expected_service: str | None = None,
    required_operation: str | None = None,
    required_result_type: str | None = None,
) -> HubCallbackTokenClaims:
    """Validate a signed session-bound hub callback token."""
    if not token:
        raise HubCallbackTokenError("hub callback token must not be empty")
    if not secret:
        raise HubCallbackTokenError("hub callback token secret must not be empty")

    parts = token.split(".")
    if len(parts) != 3:
        raise HubCallbackTokenError("hub callback token must have three parts")

    encoded_header, encoded_payload, encoded_signature = parts
    signing_input = f"{encoded_header}.{encoded_payload}"
    expected_signature = _sign(secret, signing_input)
    if not hmac.compare_digest(encoded_signature, expected_signature):
        raise HubCallbackTokenError("hub callback token signature is invalid")

    try:
        header = json.loads(_base64url_decode(encoded_header).decode("utf-8"))
        payload = json.loads(_base64url_decode(encoded_payload).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HubCallbackTokenError("hub callback token is not valid JSON") from exc

    if header.get("alg") != "HS256":
        raise HubCallbackTokenError("hub callback token algorithm is invalid")
    if header.get("typ") != HUB_CALLBACK_TOKEN_TYPE:
        raise HubCallbackTokenError("hub callback token type is invalid")

    try:
        claims = HubCallbackTokenClaims.model_validate(payload)
    except ValidationError as exc:
        raise HubCallbackTokenError("hub callback token claims are invalid") from exc

    timestamp = int((now or datetime.now(UTC)).timestamp())
    if claims.nbf > timestamp:
        raise HubCallbackTokenError("hub callback token is not valid yet")
    if claims.exp <= timestamp:
        raise HubCallbackTokenError("hub callback token is expired")
    if expected_service is not None and claims.service != expected_service:
        raise HubCallbackTokenError("hub callback token service is invalid")
    if required_operation is not None and required_operation not in claims.ops:
        raise HubCallbackTokenError("hub callback token operation is not allowed")
    if (
        required_result_type is not None
        and claims.result_types
        and required_result_type not in claims.result_types
    ):
        raise HubCallbackTokenError("hub callback token result type is not allowed")
    return claims


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(secret: str, value: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).digest()
    return _base64url_encode(digest)


def _signing_input(header: dict[str, str], payload: dict[str, object]) -> str:
    encoded_header = _base64url_encode(
        json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    encoded_payload = _base64url_encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return f"{encoded_header}.{encoded_payload}"


def resolve_service_principal(
    token: str,
    registry: ServiceRegistry,
) -> ServicePrincipal | None:
    """Resolve a callback token to its registered service principal."""
    if not token:
        return None

    for service_config in registry.all_service_configs:
        callback_token = service_config.hub_callback_token
        if not callback_token:
            continue
        if not secrets.compare_digest(callback_token, token):
            continue

        return resolve_service_principal_by_name(service_config.name, registry)

    return None


def resolve_service_principal_by_name(
    service_name: str,
    registry: ServiceRegistry,
) -> ServicePrincipal | None:
    """Resolve a registered service name to its hub principal."""
    if not service_name:
        return None

    for service_config in registry.all_service_configs:
        if service_config.name != service_name:
            continue

        capabilities = registry.service_hub_capabilities(service_config.name)
        logger.debug("Resolved hub callback principal", service=service_config.name)
        return ServicePrincipal(
            service_name=service_config.name,
            result_types=capabilities.result_types,
            can_publish=capabilities.can_publish_results,
            can_consume=capabilities.can_consume_results,
        )

    return None
