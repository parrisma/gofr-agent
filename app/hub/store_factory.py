"""Factory for constructing the configured hub result store."""

from __future__ import annotations

from app.config import GofrAgentConfig
from app.hub.clock import Clock
from app.hub.external_cache_store import ExternalCacheResultStore
from app.hub.store import ResultStore
from app.hub.store_types import HubResultStore


def create_result_store(
    config: GofrAgentConfig,
    *,
    clock: Clock | None = None,
) -> HubResultStore:
    """Return the configured hub result store backend."""
    if config.hub_store_backend == "memory":
        return ResultStore(config, clock=clock)
    return ExternalCacheResultStore(config, clock=clock)
