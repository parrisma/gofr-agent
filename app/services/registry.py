"""Service registry — manages pools and discovered tools for all MCP services."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from fnmatch import fnmatchcase
from urllib.parse import urlsplit

from app.config import GofrAgentConfig
from app.exceptions import ServiceRegistrationPolicyError
from app.logger import get_logger
from app.request_context import request_log_fields
from app.services import ServiceConfig, ServicesManifest
from app.services.discovery import MCPToolInfo, discover_tools
from app.services.pool import SessionPool

logger = get_logger("gofr-agent.registry")


@dataclass
class ServiceHealth:
    status: str
    error: str | None = None


class ServiceRegistry:
    """Manages :class:`SessionPool` instances and discovered tools per service."""

    def __init__(self, config: GofrAgentConfig) -> None:
        self._config = config
        self._services: dict[str, ServiceConfig] = {}
        self._pools: dict[str, SessionPool] = {}
        self._tools: dict[str, list[MCPToolInfo]] = {}
        self._health: dict[str, ServiceHealth] = {}
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
                logger.debug(
                    "Skipping disabled service",
                    service=svc.name,
                    **request_log_fields(),
                )
                continue
            try:
                await self._register_one(svc)
            except Exception as exc:
                logger.warning(
                    "Could not register service; skipping",
                    service=svc.name,
                    error=str(exc),
                    **request_log_fields(),
                )

    async def register_service(self, config: ServiceConfig) -> list[MCPToolInfo]:
        """Register a single service, replacing any existing registration.

        Returns the list of discovered tools for the service.
        """
        self._validate_dynamic_registration(config)
        async with self._lock:
            old_pool = self._pools.pop(config.name, None)
            if old_pool is not None:
                await old_pool.stop()
            self._tools.pop(config.name, None)
            try:
                tools = await self._register_one(config)
            except Exception as exc:
                self._record_failure(config, str(exc))
                raise
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

    def service_status(self, name: str) -> str:
        pool = self._pools.get(name)
        if pool is not None:
            return "healthy" if pool.is_healthy else "degraded"
        return self._health.get(name, ServiceHealth(status="failed")).status

    def service_error(self, name: str) -> str | None:
        return self._health.get(name, ServiceHealth(status="failed")).error

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_dynamic_registration(self, svc: ServiceConfig) -> None:
        if not self._config.dynamic_registration_enabled:
            raise ServiceRegistrationPolicyError("dynamic registration is disabled")

        allowed_hosts = [host.strip().lower() for host in self._config.allowed_service_hosts]
        if not allowed_hosts:
            raise ServiceRegistrationPolicyError("allowed_service_hosts must not be empty")

        host = urlsplit(svc.url).hostname
        if host is None:
            raise ServiceRegistrationPolicyError(
                f"Service URL must include a hostname: {svc.url}"
            )
        lowered_host = host.lower()
        if not any(fnmatchcase(lowered_host, pattern) for pattern in allowed_hosts):
            raise ServiceRegistrationPolicyError(
                f"Service host '{host}' is not in allowed_service_hosts"
            )

    def _record_failure(self, svc: ServiceConfig, error: str) -> None:
        self._services[svc.name] = svc
        self._tools[svc.name] = []
        self._health[svc.name] = ServiceHealth(status="failed", error=error)

    def _record_success(self, svc: ServiceConfig, pool: SessionPool) -> None:
        self._services[svc.name] = svc
        self._health[svc.name] = ServiceHealth(
            status="healthy" if pool.is_healthy else "degraded"
        )

    async def _register_one(self, svc: ServiceConfig) -> list[MCPToolInfo]:
        pool = SessionPool(svc, pool_size=self._config.session_pool_size)
        try:
            await pool.start()
            tools = await discover_tools(pool, svc)
        except Exception:
            await pool.stop()
            raise
        self._pools[svc.name] = pool
        self._tools[svc.name] = tools
        self._record_success(svc, pool)
        logger.info(
            "Registered service",
            service=svc.name,
            tool_count=len(tools),
            **request_log_fields(),
        )
        return tools
