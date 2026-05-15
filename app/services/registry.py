"""Service registry — manages pools and discovered tools for all MCP services."""

from __future__ import annotations

import asyncio
import logging

from app.config import GofrAgentConfig
from app.services import ServiceConfig, ServicesManifest
from app.services.discovery import MCPToolInfo, discover_tools
from app.services.pool import SessionPool

logger = logging.getLogger(__name__)


class ServiceRegistry:
    """Manages :class:`SessionPool` instances and discovered tools per service."""

    def __init__(self, config: GofrAgentConfig) -> None:
        self._config = config
        self._services: dict[str, ServiceConfig] = {}
        self._pools: dict[str, SessionPool] = {}
        self._tools: dict[str, list[MCPToolInfo]] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    async def load_manifest(self, manifest: ServicesManifest) -> None:
        """Register all *enabled* services from *manifest*.

        Unreachable or failing services are skipped with a warning —
        the registry continues operating in degraded mode.
        """
        for svc in manifest.services:
            if not svc.enabled:
                logger.debug("Skipping disabled service '%s'.", svc.name)
                continue
            try:
                await self._register_one(svc)
            except Exception as exc:
                logger.warning(
                    "Could not register service '%s': %s — skipping.", svc.name, exc
                )

    async def register_service(self, config: ServiceConfig) -> list[MCPToolInfo]:
        """Register a single service, replacing any existing registration.

        Returns the list of discovered tools for the service.
        """
        async with self._lock:
            # Tear down existing pool if present
            if config.name in self._pools:
                await self._pools[config.name].stop()
            tools = await self._register_one(config)
        return tools

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Stop all active pools."""
        async with self._lock:
            for pool in self._pools.values():
                await pool.stop()
            self._pools.clear()
            self._services.clear()
            self._tools.clear()

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def all_tools(self) -> list[MCPToolInfo]:
        """Flat list of all discovered tools across all registered services."""
        result: list[MCPToolInfo] = []
        for tools in self._tools.values():
            result.extend(tools)
        return result

    @property
    def all_pools(self) -> dict[str, SessionPool]:
        return dict(self._pools)

    @property
    def all_service_configs(self) -> list[ServiceConfig]:
        return list(self._services.values())

    def get_pool(self, name: str) -> SessionPool | None:
        return self._pools.get(name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _register_one(self, svc: ServiceConfig) -> list[MCPToolInfo]:
        pool = SessionPool(svc, pool_size=self._config.session_pool_size)
        await pool.start()
        tools = await discover_tools(pool, svc)
        self._pools[svc.name] = pool
        self._services[svc.name] = svc
        self._tools[svc.name] = tools
        logger.info(
            "Registered service '%s' with %d tool(s).", svc.name, len(tools)
        )
        return tools
