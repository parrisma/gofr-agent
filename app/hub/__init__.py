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
    from app.hub.auth import ServicePrincipal, resolve_service_principal
    from app.hub.store import ResultStore
    from app.hub.store_factory import create_result_store
    from app.hub.store_types import HubAccessScope, HubResultStore, HubStoreHealth


def __getattr__(name: str) -> Any:
    if name == "ResultStore":
        from app.hub.store import ResultStore

        return ResultStore
    if name == "create_result_store":
        from app.hub.store_factory import create_result_store

        return create_result_store
    if name in {"HubAccessScope", "HubResultStore", "HubStoreHealth"}:
        from app.hub.store_types import HubAccessScope, HubResultStore, HubStoreHealth

        return {
            "HubAccessScope": HubAccessScope,
            "HubResultStore": HubResultStore,
            "HubStoreHealth": HubStoreHealth,
        }[name]
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
    "HubAccessScope",
    "HubResultStore",
    "HubStoreHealth",
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
    "create_result_store",
    "resolve_service_principal",
]
