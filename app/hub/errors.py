"""Structured hub error helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from mcp import McpError
from mcp.types import INVALID_PARAMS, ErrorData

HUB_INVALID_PROTOCOL_VERSION = "hub.invalid_protocol_version"
HUB_UNAUTHORISED = "hub.unauthorised"
HUB_UNREGISTERED_SERVICE = "hub.unregistered_service"
HUB_REGISTRATION_REQUIRED = "hub.registration_required"
HUB_RESULT_TYPE_NOT_ALLOWED = "hub.result_type_not_allowed"
HUB_UNKNOWN_RESULT = "hub.unknown_result"
HUB_EXPIRED_RESULT = "hub.expired_result"
HUB_OVERSIZED_RESULT = "hub.oversized_result"
HUB_CAPACITY_EXCEEDED = "hub.capacity_exceeded"
HUB_MALFORMED_REQUEST = "hub.malformed_request"
HUB_SCHEMA_MISMATCH = "hub.schema_mismatch"

ALL_HUB_ERROR_CODES = (
    HUB_INVALID_PROTOCOL_VERSION,
    HUB_UNAUTHORISED,
    HUB_UNREGISTERED_SERVICE,
    HUB_REGISTRATION_REQUIRED,
    HUB_RESULT_TYPE_NOT_ALLOWED,
    HUB_UNKNOWN_RESULT,
    HUB_EXPIRED_RESULT,
    HUB_OVERSIZED_RESULT,
    HUB_CAPACITY_EXCEEDED,
    HUB_MALFORMED_REQUEST,
    HUB_SCHEMA_MISMATCH,
)


@dataclass(frozen=True)
class HubError(Exception):
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


def raise_hub_error(code: str, message: str) -> NoReturn:
    raise HubError(code=code, message=message)


def hub_mcp_error(code: str, message: str) -> McpError:
    return McpError(
        ErrorData(
            code=INVALID_PARAMS,
            message=f"{code}: {message}",
            data={"hub_code": code},
        )
    )
