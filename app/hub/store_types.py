"""Generic hub store abstractions shared by all backends."""

from __future__ import annotations

from typing import Literal, Protocol

from app.hub.models import (
    DescribeResultRequest,
    DescribeResultResponse,
    GetResultRequest,
    GetResultResponse,
    HubModel,
    ResultDescriptor,
    StoreResultRequest,
)

HUB_OPERATION_STORE = "store"
HUB_OPERATION_GET = "get"
HUB_OPERATION_DESCRIBE = "describe"


class HubAccessScope(HubModel):
    """Trusted hub access context resolved by gofr-agent."""

    session_namespace: str
    principal_service: str
    allowed_operations: tuple[str, ...] = ()
    allowed_result_types: tuple[str, ...] = ()
    session_id: str | None = None
    request_id: str | None = None
    run_id: str | None = None


class HubStoreHealth(HubModel):
    """Backend-agnostic health view for the results hub store."""

    backend: Literal["memory", "external_cache"]
    status: Literal["healthy", "degraded", "failed"]
    reachable: bool
    error: str | None = None
    indexed_result_count: int | None = None


class HubResultStore(Protocol):
    """Protocol implemented by all hub result-store backends."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def health(self) -> HubStoreHealth: ...

    async def store(
        self,
        scope: HubAccessScope,
        request: StoreResultRequest,
    ) -> ResultDescriptor: ...

    async def get(
        self,
        scope: HubAccessScope,
        request: GetResultRequest,
    ) -> GetResultResponse: ...

    async def describe(
        self,
        scope: HubAccessScope,
        request: DescribeResultRequest,
    ) -> DescribeResultResponse: ...
