"""Hub helpers for MCP result handoff."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.hub.models import (
    DESCRIBE_RESULT_TOOL,
    GET_RESULT_TOOL,
    REGISTER_RESULTS_HUB_TOOL,
    STORE_RESULT_TOOL,
    DescribeResultRequest,
    DescribeResultResponse,
    GetResultRequest,
    GetResultResponse,
    RegisterResultsHubRequest,
    RegisterResultsHubResponse,
    ResultDescriptor,
    ResultMetadata,
    StoreResultRequest,
    StoreResultResponse,
)

if TYPE_CHECKING:
    from app.hub.auth import ServicePrincipal
    from app.hub.store import ResultStore


def __getattr__(name: str) -> Any:
    if name == "ResultStore":
        from app.hub.store import ResultStore

        return ResultStore
    if name in {"ServicePrincipal", "resolve_service_principal"}:
        from app.hub.auth import ServicePrincipal, resolve_service_principal

        return {
            "ServicePrincipal": ServicePrincipal,
            "resolve_service_principal": resolve_service_principal,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "DescribeResultRequest",
    "DescribeResultResponse",
    "DESCRIBE_RESULT_TOOL",
    "GET_RESULT_TOOL",
    "GetResultRequest",
    "GetResultResponse",
    "RegisterResultsHubRequest",
    "RegisterResultsHubResponse",
    "REGISTER_RESULTS_HUB_TOOL",
    "ResultDescriptor",
    "ResultMetadata",
    "ResultStore",
    "ServicePrincipal",
    "STORE_RESULT_TOOL",
    "StoreResultRequest",
    "StoreResultResponse",
    "resolve_service_principal",
]
