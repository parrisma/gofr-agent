from __future__ import annotations

from app.config import GofrAgentConfig
from app.hub.external_cache_store import ExternalCacheResultStore
from app.hub.store import ResultStore
from app.hub.store_factory import create_result_store


class TestCreateResultStore:
    def test_memory_backend_returns_result_store(self) -> None:
        store = create_result_store(GofrAgentConfig())

        assert isinstance(store, ResultStore)

    def test_external_cache_backend_returns_external_cache_store(self) -> None:
        config = GofrAgentConfig(
            hub_store_backend="external_cache",
            hub_cache_url="redis://gofr-agent-valkey:6379/0",
        )

        store = create_result_store(config)

        assert isinstance(store, ExternalCacheResultStore)
